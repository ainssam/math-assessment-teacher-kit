"""Collect a historical Schoolinfo 4-ga attachment corpus into this project.

The upstream MCP collector accepts a year but replaces it with the current item
year returned by Schoolinfo.  This project-local runner deliberately uses the
requested historical year in JG_YEAR/JG_YEAR2/CHOSEN_JG_YEAR/PRE_JG_YEAR while
keeping original files and a resumable provenance log separate from 2026 data.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def safe_name(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", value).strip("_")[:150] or "schoolinfo_attachment"


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.stem + "_", suffix=".partial", dir=path.parent)
    os.close(fd)
    temp = Path(name)
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def atomic_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.stem + "_", suffix=".partial", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument(
        "--collector-scripts",
        type=Path,
        default=Path(__file__).resolve().parent / "schoolinfo_vendor",
        help="vendored Schoolinfo helper modules (defaults to this project's scripts/schoolinfo_vendor)",
    )
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--sleep-seconds", type=float, default=0.5)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--sido", default="")
    args = parser.parse_args()

    project = args.project_root.resolve()
    derived = project / "data" / "derived"
    roster = derived / "schoolinfo_schools.csv"
    raw_root = project / "data" / "raw" / "schoolinfo" / "4ga_by_year" / str(args.year)
    final_log = derived / f"schoolinfo_4ga_{args.year}_collection.jsonl"
    working_log = derived / f"schoolinfo_4ga_{args.year}_collection.inprogress.jsonl"
    summary_path = derived / f"schoolinfo_4ga_{args.year}_collection_summary.json"
    if final_log.exists() or summary_path.exists():
        raise SystemExit(f"historical collection output already exists for {args.year}")

    collector_scripts = args.collector_scripts.resolve()
    required_modules = (
        "collect_schoolinfo_item_attachments.py",
        "pilot_2ga_http.py",
        "schoolinfo_2ga_request_audit.py",
        "schoolinfo_documents_core.py",
        "schoolinfo_2ga_metadata_rows.py",
    )
    missing_modules = [name for name in required_modules if not (collector_scripts / name).exists()]
    if missing_modules:
        raise SystemExit(f"collector helper modules missing from {collector_scripts}: {missing_modules}")
    sys.path.insert(0, str(collector_scripts))
    from collect_schoolinfo_item_attachments import named_attachments
    from pilot_2ga_http import HANGMOK_URL, ItemRequest, download, fetch_item_html, opener, params_from_item, post, resolve_shl_idf
    from schoolinfo_2ga_request_audit import classify_download_payload, classify_response_html, html_title
    from schoolinfo_documents_core import School

    schools: list[School] = []
    with roster.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if args.sido and row.get("region_sido") != args.sido:
                continue
            schools.append(School(
                school_id=str(row.get("school_id") or ""),
                school_name=str(row.get("school_name") or ""),
                region_sido=str(row.get("region_sido") or row.get("region") or ""),
                region_sgg=str(row.get("region_sgg") or row.get("district") or ""),
                school_code=str(row.get("school_code") or ""),
                neis_school_code=str(row.get("neis_school_code") or ""),
                education_office_code=str(row.get("education_office_code") or ""),
            ))
    schools.sort(key=lambda value: (value.region_sido, value.region_sgg, value.school_name, value.school_code))
    selected = schools[args.offset: args.offset + args.limit if args.limit else None]

    completed_schools: set[str] = set()
    prior_records = 0
    if working_log.exists():
        with working_log.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                prior_records += 1
                if record.get("record_type") == "school_summary":
                    completed_schools.add(str(record.get("school_code") or ""))
    pending = [school for school in selected if school.school_code not in completed_schools]

    def collect_school(school: School) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        browser = opener()
        time.sleep(max(0.0, args.sleep_seconds))
        uid, lookup_error = resolve_shl_idf(browser, school)
        source_url = "https://www.schoolinfo.go.kr/ei/pp/Pneipp_b43_s0p.do"
        if lookup_error or not uid:
            records.append({
                "record_type": "failure", "year": args.year, "school_code": school.school_code,
                "school_name": school.school_name, "region": school.region_sido,
                "result": "failed", "failure_reason": lookup_error or "school_uuid_missing",
                "source_url": source_url, "collected_at": now(),
            })
        else:
            source_url += f"?SHL_IDF_CD={uid}"
            try:
                response = post(browser, HANGMOK_URL, {"SHL_IDF_CD": uid}, 15)
                payload = json.loads(response.body)
                item = next(row for row in payload if isinstance(row, dict) and row.get("GS_HANGMOK_NO") == "4-가")
                request = ItemRequest(str(item.get("GS_URL", "/ei/pp/Pneipp_b43_s0p.do")), params_from_item(item, str(args.year), uid))
                page = fetch_item_html(browser, request)
                attachments = named_attachments(page.body, request)
                if not attachments:
                    classification = classify_response_html(int(page.status_code or "0"), page.body)
                    records.append({
                        "record_type": "school_result", "year": args.year, "school_code": school.school_code,
                        "school_name": school.school_name, "region": school.region_sido,
                        "result": "no_attachment", "status_detail": classification.error_pattern or html_title(page.body),
                        "source_url": source_url, "collected_at": now(),
                    })
                for attachment in attachments:
                    try:
                        downloaded = download(browser, attachment.download_url)
                        validation = classify_download_payload(downloaded.body, downloaded.content_type)
                        if not validation.is_valid:
                            raise RuntimeError(f"download_validation_failed:{validation.reason}")
                        digest = hashlib.sha256(downloaded.body).hexdigest()
                        suffix = Path(attachment.filename).suffix or ".bin"
                        target_dir = raw_root / safe_name(school.region_sido) / safe_name(school.school_name)
                        target_dir.mkdir(parents=True, exist_ok=True)
                        matches = sorted(target_dir.glob(f"{school.school_code}_{digest[:12]}_*"))
                        target = matches[0] if matches else target_dir / f"{school.school_code}_{digest[:12]}_{safe_name(Path(attachment.filename).stem)}{suffix}"
                        if not target.exists():
                            atomic_bytes(target, downloaded.body)
                        records.append({
                            "record_type": "attachment", "year": args.year, "school_code": school.school_code,
                            "school_name": school.school_name, "region": school.region_sido,
                            "candidate_name": attachment.filename, "file_seq": attachment.file_seq,
                            "result": "downloaded", "status_detail": validation.detected_type,
                            "saved_path": target.relative_to(project).as_posix(), "sha256": digest,
                            "size_bytes": len(downloaded.body), "source_url": source_url,
                            "final_url": attachment.download_url, "collected_at": now(),
                        })
                    except Exception as exc:
                        records.append({
                            "record_type": "attachment", "year": args.year, "school_code": school.school_code,
                            "school_name": school.school_name, "region": school.region_sido,
                            "candidate_name": attachment.filename, "file_seq": attachment.file_seq,
                            "result": "failed", "failure_reason": f"{type(exc).__name__}:{exc}",
                            "source_url": source_url, "final_url": attachment.download_url, "collected_at": now(),
                        })
            except Exception as exc:
                records.append({
                    "record_type": "failure", "year": args.year, "school_code": school.school_code,
                    "school_name": school.school_name, "region": school.region_sido,
                    "result": "failed", "failure_reason": f"{type(exc).__name__}:{exc}",
                    "source_url": source_url, "collected_at": now(),
                })
        downloaded_count = sum(record.get("result") == "downloaded" for record in records)
        failed_count = sum(record.get("result") == "failed" for record in records)
        no_attachment = sum(record.get("result") == "no_attachment" for record in records)
        records.append({
            "record_type": "school_summary", "year": args.year, "school_code": school.school_code,
            "school_name": school.school_name, "region": school.region_sido,
            "downloaded": downloaded_count, "failed": failed_count, "no_attachment": no_attachment,
            "result": "complete" if failed_count == 0 else "complete_with_failures", "collected_at": now(),
        })
        return records

    derived.mkdir(parents=True, exist_ok=True)
    mode = "a" if working_log.exists() else "w"
    with working_log.open(mode, encoding="utf-8", newline="\n") as output:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            for index, records in enumerate(pool.map(collect_school, pending), 1):
                for record in records:
                    output.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                output.flush()
                if index % 25 == 0 or index == len(pending):
                    print(json.dumps({
                        "year": args.year, "processed_this_run": index, "pending_this_run": len(pending),
                        "selected_schools": len(selected), "resumed_schools": len(completed_schools),
                    }, ensure_ascii=False), flush=True)

    os.replace(working_log, final_log)
    counts: dict[str, int] = {}
    attachment_files = attachment_bytes = schools_attempted = 0
    with final_log.open("r", encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            result = str(record.get("result") or "unknown")
            counts[result] = counts.get(result, 0) + 1
            if record.get("record_type") == "attachment" and result == "downloaded":
                attachment_files += 1
                attachment_bytes += int(record.get("size_bytes") or 0)
            if record.get("record_type") == "school_summary":
                schools_attempted += 1
    summary = {
        "year": args.year, "selected_schools": len(selected), "schools_attempted": schools_attempted,
        "attachment_files": attachment_files, "attachment_bytes": attachment_bytes,
        "result_counts": counts, "prior_records_resumed": prior_records,
        "raw_root": str(raw_root), "log": str(final_log), "completed_at": now(),
    }
    atomic_json(summary_path, summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
