"""Wait for full extraction, retry incomplete rows, and build validated final artifacts."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


INITIAL_TOTAL = 5060
BATCH_SIZE = 500
EXPECTED_SOURCE_ROWS = 13357


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def log(handle, event: str, **values: object) -> None:
    record = {"time": now(), "event": event, **values}
    line = json.dumps(record, ensure_ascii=False)
    handle.write(line + "\n")
    handle.flush()
    print(line, flush=True)


def jsonl_count(path: Path) -> tuple[int, int]:
    rows = bad = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            rows += 1
    return rows, bad


def wait_for_initial(derived: Path, handle) -> None:
    offsets = list(range(0, INITIAL_TOTAL, BATCH_SIZE))
    last_rows = -1
    while True:
        rows = bad = completed = 0
        for offset in offsets:
            path = derived / f"math_allplan_remaining_text_{offset:04d}.jsonl"
            if not path.exists():
                continue
            count, malformed = jsonl_count(path)
            expected = min(BATCH_SIZE, INITIAL_TOTAL - offset)
            if count == expected and malformed == 0:
                rows += count
                completed += 1
            else:
                bad += malformed
        if rows != last_rows:
            log(handle, "initial_extraction_progress", rows=rows, expected=INITIAL_TOTAL, completed_files=completed, expected_files=len(offsets), bad_json=bad)
            last_rows = rows
        if rows == INITIAL_TOTAL and completed == len(offsets) and bad == 0:
            return
        time.sleep(15)


def run_step(handle, name: str, command: list[str], outputs: list[Path]) -> None:
    if outputs and all(path.exists() for path in outputs):
        log(handle, "step_reused", step=name, outputs=[str(path) for path in outputs])
        return
    log(handle, "step_started", step=name, command=command)
    completed = subprocess.run(command, text=True, encoding="utf-8", errors="replace", capture_output=True)
    log(handle, "step_finished", step=name, returncode=completed.returncode, stdout=completed.stdout[-4000:], stderr=completed.stderr[-4000:])
    if completed.returncode:
        raise SystemExit(f"{name} failed with exit code {completed.returncode}")
    missing = [str(path) for path in outputs if not path.exists()]
    if missing:
        raise SystemExit(f"{name} did not create outputs: {missing}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    args = parser.parse_args()
    project = args.project_root.resolve()
    derived = project / "data" / "derived"
    scripts = project / "scripts"
    python = Path(sys.executable)
    kordoc = scripts / "kordoc-fixed.cmd"
    log_path = derived / "math_assessment_final_pipeline.log.jsonl"
    completion = derived / "math_assessment_final_pipeline_completion.json"
    if completion.exists():
        raise SystemExit(f"completion marker already exists: {completion}")

    with log_path.open("a", encoding="utf-8", newline="\n") as handle:
        log(handle, "pipeline_started", project=str(project), python=str(python))
        wait_for_initial(derived, handle)

        retry_queue = derived / "math_assessment_retry_queue_v2.jsonl"
        retry_summary = derived / "math_assessment_retry_queue_v2_summary.json"
        run_step(handle, "build_retry_queue", [
            str(python), str(scripts / "build_math_extraction_retry_queue.py"),
            "--derived-dir", str(derived), "--output", str(retry_queue),
            "--summary-output", str(retry_summary),
        ], [retry_queue, retry_summary])
        retry_rows, retry_bad = jsonl_count(retry_queue)
        if retry_bad:
            raise SystemExit(f"retry queue has {retry_bad} malformed rows")

        retry_output = derived / "math_assessment_retry_fulltext_v2.jsonl"
        if retry_rows:
            run_step(handle, "retry_incomplete_extraction", [
                str(python), str(scripts / "extract_math_candidate_text.py"),
                "--input-jsonl", str(retry_queue), "--project-root", str(project),
                "--kordoc", str(kordoc), "--output", str(retry_output),
                "--offset", "0", "--limit", str(retry_rows), "--workers", "8",
            ], [retry_output])
        elif not retry_output.exists():
            retry_output.write_text("", encoding="utf-8")

        evidence_prefix = "math_assessment_all_subject_evidence_v2"
        evidence_source = derived / f"{evidence_prefix}_source.jsonl"
        evidence_index = derived / f"{evidence_prefix}_index.jsonl"
        evidence_summary = derived / f"{evidence_prefix}_summary.json"
        evidence_command = [
            str(python), str(scripts / "build_math_assessment_evidence_index.py"),
            "--derived-dir", str(derived), "--output-prefix", evidence_prefix,
        ]
        if retry_rows:
            evidence_command += ["--replacement-jsonl", str(retry_output)]
        run_step(handle, "build_all_subject_evidence", evidence_command, [evidence_source, evidence_index, evidence_summary])

        strict = derived / "math_assessment_strict_all_subjects_v2.jsonl"
        shortlist = derived / "math_assessment_model_shortlist_v2.jsonl"
        strict_summary = derived / "math_assessment_strict_all_subjects_v2_summary.json"
        run_step(handle, "build_strict_all_subject_catalog", [
            str(python), str(scripts / "build_strict_math_shortlist.py"),
            "--input", str(evidence_index), "--strict-output", str(strict),
            "--shortlist-output", str(shortlist), "--summary-output", str(strict_summary),
            "--per-subject", "25",
        ], [strict, shortlist, strict_summary])

        catalog = derived / "math_assessment_school_subject_catalog_v2.jsonl"
        coverage = derived / "math_assessment_school_subject_coverage_v2.csv"
        coverage_summary = derived / "math_assessment_school_subject_coverage_v2_summary.json"
        schools = derived / "schoolinfo_schools.csv"
        manifest = derived / "math_assessment_source_manifest.csv"
        run_step(handle, "build_school_subject_coverage", [
            str(python), str(scripts / "build_school_subject_assessment_catalog.py"),
            "--schools", str(schools), "--manifest", str(manifest),
            "--source-index", str(evidence_source), "--strict-input", str(strict),
            "--catalog-output", str(catalog), "--coverage-output", str(coverage),
            "--summary-output", str(coverage_summary),
        ], [catalog, coverage, coverage_summary])

        trends_csv = derived / "math_assessment_subject_trends_v2.csv"
        trends_json = derived / "math_assessment_subject_trends_v2.json"
        run_step(handle, "build_subject_trends", [
            str(python), str(scripts / "build_math_assessment_trends.py"),
            "--catalog", str(catalog), "--csv-output", str(trends_csv),
            "--json-output", str(trends_json),
        ], [trends_csv, trends_json])

        validation = derived / "math_assessment_catalog_validation_v2.json"
        run_step(handle, "validate_final_outputs", [
            str(python), str(scripts / "validate_math_assessment_catalog.py"),
            "--schools", str(schools), "--source-index", str(evidence_source),
            "--evidence-index", str(evidence_index), "--strict-index", str(strict),
            "--catalog", str(catalog), "--coverage", str(coverage),
            "--report", str(validation), "--expected-source-rows", str(EXPECTED_SOURCE_ROWS),
        ], [validation])

        payload = {
            "completed_at": now(), "source_rows_expected": EXPECTED_SOURCE_ROWS,
            "remaining_rows_extracted": INITIAL_TOTAL, "retry_rows": retry_rows,
            "outputs": [str(path) for path in (
                evidence_source, evidence_index, evidence_summary, strict, shortlist,
                strict_summary, catalog, coverage, coverage_summary, trends_csv,
                trends_json, validation,
            )],
        }
        temp = completion.with_suffix(".partial")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, completion)
        log(handle, "pipeline_completed", **payload)


if __name__ == "__main__":
    main()
