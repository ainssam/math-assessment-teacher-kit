"""Re-download failed Schoolinfo attachments without replacing preserved originals."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-jsonl", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--manifest-output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=90)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project = args.project_root.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    with args.input_jsonl.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                record = json.loads(line)
                if record.get("extract_status") == "failed":
                    rows.append(record)

    results: list[dict[str, object]] = []
    for index, record in enumerate(rows, 1):
        source = record.get("source") or {}
        saved_path = project / str(source.get("saved_path") or "")
        url = str(source.get("final_url") or "")
        source_url = str(source.get("source_url") or "")
        suffix = saved_path.suffix.lower()
        stem = hashlib.sha256(str(saved_path).encode("utf-8")).hexdigest()[:16]
        target = output_dir / f"{stem}{suffix}"
        result: dict[str, object] = {
            "school_code": source.get("school_code", ""),
            "school_name": source.get("school_name", ""),
            "candidate_name": source.get("candidate_name", ""),
            "original_path": str(saved_path),
            "original_bytes": saved_path.stat().st_size if saved_path.is_file() else 0,
            "original_sha256": sha256(saved_path) if saved_path.is_file() else "",
            "source_url": source_url,
            "final_url": url,
            "recovery_path": str(target),
        }
        if not url:
            result.update(status="missing_final_url", error="")
            results.append(result)
            continue
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; MathAssessmentArchiveRecovery/1.0)",
                "Referer": source_url,
                "Accept": "application/octet-stream,*/*;q=0.8",
            },
        )
        fd, temp_name = tempfile.mkstemp(prefix=target.stem + "_", suffix=".partial", dir=output_dir)
        os.close(fd)
        temp_path = Path(temp_name)
        try:
            with urllib.request.urlopen(request, timeout=args.timeout) as response, temp_path.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                content_type = response.headers.get("Content-Type", "")
            header = temp_path.read_bytes()[:16]
            if not header or header.lstrip().lower().startswith(b"<!doctype html") or header.lstrip().lower().startswith(b"<html"):
                result.update(status="html_or_empty_response", error="", content_type=content_type)
                temp_path.unlink(missing_ok=True)
            else:
                os.replace(temp_path, target)
                result.update(
                    status="downloaded",
                    error="",
                    content_type=content_type,
                    recovery_bytes=target.stat().st_size,
                    recovery_sha256=sha256(target),
                    same_as_original=bool(saved_path.is_file() and sha256(saved_path) == sha256(target)),
                    header_hex=header.hex(),
                )
        except (OSError, urllib.error.URLError) as exc:
            temp_path.unlink(missing_ok=True)
            result.update(status="download_failed", error=f"{type(exc).__name__}: {exc}")
        results.append(result)
        print(f"progress={index}/{len(rows)} status={result['status']}", flush=True)

    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "input": str(args.input_jsonl.resolve()),
        "output_dir": str(output_dir),
        "rows": results,
    }
    args.manifest_output.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    counts: dict[str, int] = {}
    for result in results:
        status = str(result["status"])
        counts[status] = counts.get(status, 0) + 1
    print(json.dumps({"total": len(results), "status": counts}, ensure_ascii=False))


if __name__ == "__main__":
    main()
