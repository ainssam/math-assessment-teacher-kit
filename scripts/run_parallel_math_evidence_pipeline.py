"""Build the full math evidence index in balanced parallel shards.

The script preserves every existing source and partial file. Each shard writes
to a unique prefix, then the completed shard outputs are concatenated into the
final v2 evidence files through temporary files and atomic replacement. After
the merge it invokes the existing final pipeline, which reuses the evidence
outputs and runs the catalog, coverage, trends, and validation steps.
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path


EXPECTED_SOURCE_ROWS = 13_357
FINAL_PREFIX = "math_assessment_all_subject_evidence_v2"


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def count_jsonl(path: Path) -> tuple[int, int]:
    rows = bad = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                json.loads(line)
            except json.JSONDecodeError:
                bad += 1
            else:
                rows += 1
    return rows, bad


def atomic_concat(inputs: list[Path], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=output.stem + "_", suffix=".partial", dir=output.parent)
    os.close(fd)
    temp = Path(name)
    try:
        with temp.open("wb") as target:
            for source in inputs:
                with source.open("rb") as handle:
                    shutil.copyfileobj(handle, target, length=4 * 1024 * 1024)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temp, output)
    finally:
        temp.unlink(missing_ok=True)


def atomic_json(path: Path, value: object) -> None:
    fd, name = tempfile.mkstemp(prefix=path.stem + "_", suffix=".partial", dir=path.parent)
    os.close(fd)
    temp = Path(name)
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def balanced_shards(paths: list[Path], count: int) -> list[list[Path]]:
    shards: list[list[Path]] = [[] for _ in range(count)]
    sizes = [0] * count
    for path in sorted(paths, key=lambda item: item.stat().st_size, reverse=True):
        index = min(range(count), key=sizes.__getitem__)
        shards[index].append(path)
        sizes[index] += path.stat().st_size
    for shard in shards:
        shard.sort(key=lambda item: item.name)
    return shards


def run_shard(
    *, python: Path, script: Path, derived: Path, replacement: Path,
    prefix: str, inputs: list[Path], shard_index: int,
) -> dict[str, object]:
    source_output = derived / f"{prefix}_source.jsonl"
    index_output = derived / f"{prefix}_index.jsonl"
    summary_output = derived / f"{prefix}_summary.json"
    if all(path.exists() for path in (source_output, index_output, summary_output)):
        result = {
            "shard": shard_index,
            "prefix": prefix,
            "input_files": [path.name for path in inputs],
            "input_bytes": sum(path.stat().st_size for path in inputs),
            "returncode": 0,
            "stdout": "reused completed shard outputs",
            "stderr": "",
            "reused": True,
        }
        print(json.dumps({"event": "shard_reused", "time": now(), **result}, ensure_ascii=True), flush=True)
        return result
    command = [
        str(python), str(script), "--derived-dir", str(derived),
        "--output-prefix", prefix, "--replacement-jsonl", str(replacement),
    ]
    for source in inputs:
        command += ["--input-jsonl", str(source)]
    completed = subprocess.run(
        command, text=True, encoding="utf-8", errors="replace",
        capture_output=True,
    )
    result = {
        "shard": shard_index,
        "prefix": prefix,
        "input_files": [path.name for path in inputs],
        "input_bytes": sum(path.stat().st_size for path in inputs),
        "returncode": completed.returncode,
        "stdout": completed.stdout[-2000:],
        "stderr": completed.stderr[-2000:],
    }
    print(json.dumps({"event": "shard_finished", "time": now(), **result}, ensure_ascii=True), flush=True)
    return result


def merge_summaries(paths: list[Path]) -> dict[str, object]:
    summaries = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    counter_fields = (
        "extract_status", "curriculum_code_hints", "subject_label_counts",
        "action_tag_counts",
    )
    merged_counters = {field: collections.Counter() for field in counter_fields}
    for summary in summaries:
        for field in counter_fields:
            merged_counters[field].update(summary.get(field) or {})
    return {
        "input_files": [item for summary in summaries for item in summary.get("input_files", [])],
        "total_source_rows": sum(int(summary.get("total_source_rows") or 0) for summary in summaries),
        "total_subject_evidence_rows": sum(int(summary.get("total_subject_evidence_rows") or 0) for summary in summaries),
        "bad_json_rows": sum(int(summary.get("bad_json_rows") or 0) for summary in summaries),
        "duplicate_source_rows_skipped": sum(int(summary.get("duplicate_source_rows_skipped") or 0) for summary in summaries),
        "replacement_rows_loaded": max(int(summary.get("replacement_rows_loaded") or 0) for summary in summaries),
        "replacement_rows_used": sum(int(summary.get("replacement_rows_used") or 0) for summary in summaries),
        "replacement_bad_json_rows": sum(int(summary.get("replacement_bad_json_rows") or 0) for summary in summaries),
        **{field: dict(counter) for field, counter in merged_counters.items()},
        "evidence_text_limit": 12_000,
        "privacy_masking": ["email", "mobile_phone", "resident_identifier"],
        "parallel_shards": len(paths),
        "merged_at": now(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--shards", type=int, default=4)
    parser.add_argument("--run-id", default="", help="reuse a prior parallel shard run")
    args = parser.parse_args()

    project = args.project_root.resolve()
    derived = project / "data" / "derived"
    scripts = project / "scripts"
    python = Path(sys.executable)
    evidence_script = scripts / "build_math_assessment_evidence_index.py"
    replacement = derived / "math_assessment_retry_fulltext_v2.jsonl"
    completion = derived / "math_assessment_final_pipeline_completion.json"
    if completion.exists():
        raise SystemExit(f"completion marker already exists: {completion}")
    if not replacement.exists():
        raise SystemExit(f"replacement input missing: {replacement}")

    inputs = [Path(path) for path in sorted(glob.glob(str(derived / "math_subject_candidate_text_[0-9]*.jsonl")))]
    inputs += [Path(path) for path in sorted(glob.glob(str(derived / "math_allplan_remaining_text_[0-9]*.jsonl")))]
    if not inputs:
        raise SystemExit("no source candidate JSONL batches found")

    shard_count = max(1, min(args.shards, len(inputs)))
    shards = balanced_shards(inputs, shard_count)
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    shard_prefixes = [f"{FINAL_PREFIX}_parallel_{run_id}_{index:02d}" for index in range(shard_count)]
    plan = {
        "event": "parallel_plan", "time": now(), "run_id": run_id,
        "shards": [
            {
                "shard": index, "prefix": shard_prefixes[index],
                "files": [path.name for path in shard],
                "bytes": sum(path.stat().st_size for path in shard),
            }
            for index, shard in enumerate(shards)
        ],
    }
    print(json.dumps(plan, ensure_ascii=True), flush=True)

    results: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=shard_count) as pool:
        futures = [
            pool.submit(
                run_shard, python=python, script=evidence_script, derived=derived,
                replacement=replacement, prefix=shard_prefixes[index],
                inputs=shard, shard_index=index,
            )
            for index, shard in enumerate(shards)
        ]
        for future in as_completed(futures):
            results.append(future.result())
    failures = [result for result in results if result["returncode"] != 0]
    if failures:
        raise SystemExit(json.dumps({"parallel_shard_failures": failures}, ensure_ascii=True))

    shard_sources = [derived / f"{prefix}_source.jsonl" for prefix in shard_prefixes]
    shard_indexes = [derived / f"{prefix}_index.jsonl" for prefix in shard_prefixes]
    shard_summaries = [derived / f"{prefix}_summary.json" for prefix in shard_prefixes]
    final_source = derived / f"{FINAL_PREFIX}_source.jsonl"
    final_index = derived / f"{FINAL_PREFIX}_index.jsonl"
    final_summary = derived / f"{FINAL_PREFIX}_summary.json"
    for target in (final_source, final_index, final_summary):
        if target.exists():
            raise SystemExit(f"refusing to overwrite existing final evidence output: {target}")

    atomic_concat(shard_sources, final_source)
    atomic_concat(shard_indexes, final_index)
    summary = merge_summaries(shard_summaries)
    source_rows, source_bad = count_jsonl(final_source)
    evidence_rows, evidence_bad = count_jsonl(final_index)
    summary["merged_source_rows_checked"] = source_rows
    summary["merged_source_bad_json"] = source_bad
    summary["merged_evidence_rows_checked"] = evidence_rows
    summary["merged_evidence_bad_json"] = evidence_bad
    if source_rows != EXPECTED_SOURCE_ROWS or source_bad or evidence_bad:
        raise SystemExit(json.dumps({
            "merge_validation_failed": True,
            "source_rows": source_rows, "expected_source_rows": EXPECTED_SOURCE_ROWS,
            "source_bad": source_bad, "evidence_rows": evidence_rows,
            "evidence_bad": evidence_bad,
        }, ensure_ascii=True))
    atomic_json(final_summary, summary)
    print(json.dumps({
        "event": "parallel_merge_completed", "time": now(),
        "source_rows": source_rows, "evidence_rows": evidence_rows,
    }, ensure_ascii=True), flush=True)

    final_pipeline = scripts / "run_final_math_assessment_pipeline.py"
    completed = subprocess.run(
        [str(python), str(final_pipeline), "--project-root", str(project)],
        text=True, encoding="utf-8", errors="replace",
    )
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
