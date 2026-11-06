"""Build a local 4-ga semester candidate without changing the active catalog."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from build_math_assessment_manifest import classify
from collect_schoolinfo_4ga_historical import atomic_bytes, atomic_json
from extract_math_assessment_batch import extract


ROOT = Path(__file__).resolve().parents[1]
KORDOC = ROOT / "node_modules" / "kordoc" / "dist" / "cli.js"
SEMESTER = re.compile(r"(?<!\d)([12])\s*학기")
PLAN_HEADING = re.compile(r"평가\s*(?:계획|운영|안)|교수\s*[·ㆍ‧∙・\-]?\s*학습")
ACADEMIC_YEAR = re.compile(r"\b(20\d{2})\s*학년도")
ARCHIVE_MEMBER = re.compile(r"^\[zip:([^\r\n]+)\]\[(ok|short|failed)\]\n", re.M)


def semester_status(name: str, text: str, semester: int, year: int) -> str:
    filename_terms = set(SEMESTER.findall(name))
    # Use cover/subject headings. Generic policy text can mention both terms.
    lines = text[:18000].splitlines()
    headings = [
        line for index, line in enumerate(lines)
        if len(line) <= 180 and PLAN_HEADING.search(" ".join(lines[max(0, index - 2):index + 3]))
    ]
    years = set(ACADEMIC_YEAR.findall("\n".join([name, *headings])))
    if years - {str(year)}:
        return "academic_year_conflict"
    heading_terms = {term for line in headings for term in SEMESTER.findall(line)}
    signals = filename_terms | heading_terms
    if signals == {str(semester)}:
        return "confirmed"
    if len(signals) == 2:
        return "mixed_or_conflicting"
    return "other_semester" if signals else "unconfirmed"


def source_records(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def confirmed_archive_members(name: str, text: str, semester: int, year: int) -> tuple[str, Counter]:
    """Keep only verified semester members in the derived text of a bundle."""
    markers = list(ARCHIVE_MEMBER.finditer(text))
    selected = []
    decisions = Counter()
    for index, marker in enumerate(markers):
        member_name, extraction = marker.groups()
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        if extraction != "ok":
            decisions[extraction] += 1
            continue
        member_text = text[marker.end():end]
        # Preserve contradictions with a declared archive term or year. A
        # dated member can still establish the term when the bundle is generic.
        status = semester_status(f"{name} {member_name}", member_text, semester, year)
        decisions[status] += 1
        if status == "confirmed":
            selected.append(text[marker.start():end].rstrip("\n"))
    return "\n\n".join(selected), decisions


def jsonl(path: Path, rows) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--semester", type=int, choices=(1, 2), default=2)
    parser.add_argument("--workers", type=int, choices=range(1, 9), default=4)
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--snapshot", type=Path, help="bounded pilot collection directory")
    inputs.add_argument("--reconciled", type=Path, help="completed identity-audited collection directory")
    parser.add_argument("--warm-cache", action="store_true", help="extract completed receipts while collection runs")
    parser.add_argument("--revision", default="v1")
    parser.add_argument("--kordoc-cli", type=Path, default=KORDOC)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9-]+", args.revision):
        parser.error("invalid revision")
    kordoc = args.kordoc_cli.resolve()
    if not kordoc.is_file():
        parser.error("kordoc CLI not installed; run pnpm install or specify --kordoc-cli")
    round_no = 1 if args.semester == 1 else 3
    collection = ROOT / "data" / "derived" / "schoolinfo_4ga" / f"{args.year}-round-{round_no}"
    snapshot = args.snapshot or args.reconciled or collection
    converter_id = hashlib.sha256(kordoc.read_bytes()).hexdigest()[:12]
    cache = collection / f"extraction_cache_v2-{converter_id}"
    cache.mkdir(parents=True, exist_ok=True)
    if args.warm_cache:
        if args.snapshot or args.reconciled:
            parser.error("--warm-cache uses current collection receipts")
        latest = {}
        for receipt in sorted((collection / "school_receipts").glob("*.json")):
            latest[receipt.stem.rsplit("-", 1)[0]] = receipt
        rows = [
            row for receipt in latest.values()
            for row in json.loads(receipt.read_text(encoding="utf-8"))["attachments"]
        ]
        summary = {}
    else:
        summary = json.loads((snapshot / "collection_summary.json").read_text(encoding="utf-8"))
        if args.reconciled and summary.get("scope") != "reconciled_roster":
            raise SystemExit("completed reconciled roster summary required")
        if not args.snapshot and summary["unattempted_schools"]:
            raise SystemExit("collection is still incomplete; use --warm-cache for incremental extraction")
        rows = source_records(snapshot / "attachments.jsonl")
        if len(rows) != summary["attachment_rows"] or summary["missing_or_size_mismatch_paths"]:
            raise SystemExit("collection manifest and summary do not reconcile")
    files = {row["saved_path"]: row for row in rows if row["result"] == "downloaded"}
    if not files or any(row["year"] != args.year or row["disclosure_round"] != round_no for row in files.values()):
        raise SystemExit("missing or mismatched source round")

    def extract_record(row: dict) -> dict:
        sha = row["sha256"]
        path = (ROOT / row["saved_path"]).resolve()
        if not path.is_relative_to(ROOT / "data" / "raw" / "schoolinfo"):
            raise ValueError("source path outside the Schoolinfo archive")
        result_path = cache / f"{sha}{path.suffix}.json"
        if not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise ValueError("invalid SHA-256")
        if not args.warm_cache or not result_path.is_file():
            with path.open("rb") as handle:
                if hashlib.file_digest(handle, "sha256").hexdigest() != sha:
                    raise ValueError(f"source hash mismatch: {row['saved_path']}")
        if result_path.is_file():
            return json.loads(result_path.read_text(encoding="utf-8"))
        text, status = extract(path, kordoc, ROOT)
        result = {"text": text, "extract_status": status}
        atomic_json(result_path, result)
        return result

    sources = list(files.values())
    # Map one content hash per format to a representative original. Each source
    # still gets its own provenance and semester decision in the next stage.
    unique = {}
    for row in sources:
        unique.setdefault((row["sha256"], Path(row["saved_path"]).suffix), row)
    pending = [
        row for (sha, suffix), row in unique.items()
        if not (cache / f"{sha}{suffix}.json").is_file()
    ]

    def populate_cache(row: dict) -> None:
        extract_record(row)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for index, _ in enumerate(pool.map(populate_cache, pending), 1):
            if index % 50 == 0 or index == len(pending):
                print(f"extraction_cache={index}/{len(pending)}", flush=True)
    if args.warm_cache:
        return

    label = f"{snapshot.name}-" if args.snapshot or args.reconciled else ""
    output = collection / f"semester-{args.semester}-{label}{args.revision}"
    output.mkdir(exist_ok=False)
    statuses: Counter[str] = Counter()
    terms: Counter[str] = Counter()
    archive_decisions: Counter[str] = Counter()
    partial_archives = 0
    incomplete = {row["school_code"] for row in rows if row["result"] == "failed"}
    if args.reconciled:
        with (snapshot / "coverage_ledger.csv").open(encoding="utf-8-sig", newline="") as stream:
            incomplete.update(
                row["school_code"] for row in csv.DictReader(stream)
                if row["collection_status"] != "listed"
            )
    expected = 0
    manifest_fields = ["school_code", "school_name", "subject_canonical", "saved_path", "final_url"]
    with (
        (output / "manifest.csv").open("x", encoding="utf-8-sig", newline="") as manifest,
        (output / "source_decisions.jsonl").open("x", encoding="utf-8") as decisions,
    ):
        writer = csv.DictWriter(manifest, fieldnames=manifest_fields, extrasaction="ignore")
        writer.writeheader()

        def confirmed_records():
            nonlocal expected, partial_archives
            for row in sources:
                result = extract_record(row)
                text, status = result["text"], result["extract_status"]
                term = semester_status(row["candidate_name"], text if status == "ok" else "", args.semester, args.year)
                selected = text if status == "ok" else ""
                member_counts = Counter()
                if Path(row["saved_path"]).suffix.lower() == ".zip":
                    selected, member_counts = confirmed_archive_members(row["candidate_name"], text, args.semester, args.year)
                    archive_decisions.update(member_counts)
                    if member_counts:
                        if selected:
                            term = "confirmed"
                        elif term == "confirmed":
                            term = "no_confirmed_archive_members"
                        if selected and member_counts.total() != member_counts["confirmed"]:
                            partial_archives += 1
                            incomplete.add(row["school_code"])
                statuses[status] += 1
                terms[term] += 1
                if term not in {"confirmed", "other_semester"} or (term == "confirmed" and status != "ok"):
                    incomplete.add(row["school_code"])
                match, canonical, match_type = classify(row["candidate_name"])
                source = {
                    **row, "listing_url": row["source_url"], "source_url": row["final_url"],
                    "subject_match": match, "subject_canonical": canonical,
                    "match_type": match_type, "semester_status": term,
                }
                decisions.write(json.dumps({
                    **source, "extract_status": status, "char_count": len(text),
                    **({"archive_member_decisions": dict(member_counts)} if member_counts else {}),
                }, ensure_ascii=False) + "\n")
                if term == "confirmed":
                    source["confirmed_semester"] = args.semester
                    writer.writerow(source)
                    expected += 1
                    yield {
                        "source": source, "sha256": row["sha256"],
                        "extract_status": "ok" if selected else status,
                        "char_count": len(selected), "text": selected,
                    }
        jsonl(output / "confirmed_extractions.jsonl", confirmed_records())
    reconcile = {
        "year": args.year, "semester": args.semester, "disclosure_round": round_no,
        "scope": "bounded_snapshot" if args.snapshot else (
            "reconciled_roster" if args.reconciled else "preserved_roster"
        ),
        "collection": summary, "extraction_statuses": dict(statuses),
        "semester_decisions": dict(terms), "confirmed_sources": expected,
        "archive_member_decisions": dict(archive_decisions), "partially_confirmed_archives": partial_archives,
    }
    if args.reconciled:
        reconcile["reconciled_roster"] = (snapshot / "roster.csv").resolve().relative_to(ROOT).as_posix()
    atomic_json(output / "reconciliation.json", reconcile)
    atomic_json(output / "incomplete_schools.json", sorted(incomplete))
    if not expected:
        raise SystemExit("no source confirmed for this semester")

    def run(script: str, *arguments: object) -> None:
        subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / script), *map(str, arguments)],
                       cwd=ROOT, check=True)

    source = output / "evidence_source.jsonl"
    evidence = output / "evidence_index.jsonl"
    strict = output / "strict.jsonl"
    catalog = output / "catalog.jsonl"
    coverage = output / "coverage.csv"
    coverage_summary = output / "coverage_summary.json"
    validation = output / "validation.json"
    roster = snapshot / "roster.csv" if args.reconciled else collection / "roster.csv"
    if args.snapshot and (snapshot / "roster.csv").is_file():
        roster = snapshot / "roster.csv"
    elif args.snapshot:
        selected_codes = {row["school_code"] for row in rows}
        roster = output / "pilot_roster.csv"
        with (collection / "roster.csv").open(encoding="utf-8-sig", newline="") as inp:
            reader = csv.DictReader(inp)
            with roster.open("x", encoding="utf-8-sig", newline="") as out:
                writer = csv.DictWriter(out, fieldnames=reader.fieldnames)
                writer.writeheader()
                writer.writerows(row for row in reader if row["school_code"] in selected_codes)
    run("build_math_assessment_evidence_index.py", "--derived-dir", output, "--output-prefix",
        "evidence", "--input-jsonl", output / "confirmed_extractions.jsonl")
    run("build_strict_math_shortlist.py", "--input", evidence, "--strict-output", strict,
        "--shortlist-output", output / "shortlist.jsonl", "--summary-output", output / "strict_summary.json")
    run("build_school_subject_assessment_catalog.py", "--schools", roster, "--manifest", output / "manifest.csv",
        "--source-index", source, "--strict-input", strict, "--catalog-output", catalog,
        "--coverage-output", coverage, "--summary-output", coverage_summary,
        "--incomplete-schools", output / "incomplete_schools.json")
    trends = output / "trends.json"
    run("build_math_assessment_trends.py", "--catalog", catalog, "--csv-output", output / "trends.csv",
        "--json-output", trends)
    run("validate_math_assessment_catalog.py", "--schools", roster, "--source-index", source,
        "--evidence-index", evidence, "--strict-index", strict, "--catalog", catalog, "--coverage", coverage,
        "--report", validation, "--expected-source-rows", expected)
    if not json.loads(validation.read_text(encoding="utf-8"))["passed"]:
        raise SystemExit("candidate validation failed")
    database = output / "catalog_candidate.sqlite"
    run("build_math_assessment_publish_db.py", "--catalog", catalog, "--trends", trends, "--coverage-summary",
        coverage_summary, "--validation", validation, "--completion", output / "reconciliation.json",
        "--schools", roster, "--output", database, "--manifest-output", output / "catalog_manifest.json")
    run("build_math_assessment_detail_db.py", "--catalog", catalog, "--source-jsonl", source, "--base-db", database,
        "--output", output / "detail_candidate.sqlite", "--manifest-output", output / "detail_manifest.json")
    print(f"candidate_ready={output.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    main()
