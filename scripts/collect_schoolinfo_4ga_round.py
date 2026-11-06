"""Collect one explicitly verified Schoolinfo 4-ga disclosure round."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode

from collect_schoolinfo_4ga_historical import atomic_bytes, atomic_json, now, safe_name

sys.path.insert(0, str(Path(__file__).resolve().parent / "schoolinfo_vendor"))
from collect_schoolinfo_item_attachments import named_attachments  # noqa: E402
from pilot_2ga_http import (  # noqa: E402
    HANGMOK_URL,
    ItemRequest,
    download,
    fetch_item_html,
    opener,
    params_from_item,
    post,
    resolve_shl_idf,
)
from schoolinfo_2ga_request_audit import classify_download_payload, classify_response_html  # noqa: E402
from schoolinfo_documents_core import BASE_URL, School, parse_hidden_params  # noqa: E402


ITEM_PATH = "/ei/pp/Pneipp_b43_s0p.do"
DOWNLOAD_FORM = re.compile(r'<form\b[^>]*\bid="eiFileDownForm"[^>]*>(.*?)</form>', re.I | re.S)
ROUND_SELECTOR = re.compile(r'<select\b[^>]*\bid="select_trans_dt"[^>]*>(.*?)</select>', re.I | re.S)
ROUND_OPTION = re.compile(r'<option\b[^>]*\bvalue="(\d+)"[^>]*\bselected\b[^>]*>', re.I)
NON_PLAN = re.compile(r"학업\s*성적\s*관리\s*(?:규정|위원회)|협의록|회의록")
PLAN = re.compile(r"평가\s*(?:계획|운영|안)|교수\s*[·ㆍ\-]?\s*학습")
TERM = re.compile(r"([12])\s*학기")
RETRYABLE = {"lookup_failed", "round_unconfirmed", "page_failed", "attachment_failed", "stopped"}


def plan_status(filename: str) -> str:
    if NON_PLAN.search(filename) and not PLAN.search(filename):
        return "non_plan_filename"
    terms = set(TERM.findall(filename))
    if terms == {"1"}:
        return "first_semester_filename"
    if terms == {"2"}:
        return "second_semester_filename"
    return "semester_requires_content_check"


def read_roster(path: Path) -> list[School]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        schools = [
            School(*(row[field].strip() for field in School.__dataclass_fields__))
            for row in csv.DictReader(stream)
        ]
    ids = {school.school_id for school in schools}
    codes = [school.school_code for school in schools if school.school_code]
    if not schools or len(ids) != len(schools) or not all(re.fullmatch(r"[\w-]+", key) for key in ids):
        raise ValueError("roster must contain unique safe school IDs")
    if len(codes) != len(set(codes)) or not all(re.fullmatch(r"[A-Za-z0-9]+", code) for code in codes):
        raise ValueError("nonempty school codes must be unique and alphanumeric")
    return schools


def collect_school(
    school: School, project: Path, raw: Path, year: int, round_no: int,
    pause: float, stop: threading.Event,
) -> dict:
    identity = {
        "school_id": school.school_id, "school_code": school.school_code, "school_name": school.school_name,
        "region": school.region_sido, "region_sgg": school.region_sgg,
        "item_no": "4-가", "year": year, "disclosure_round": round_no,
    }
    record = {**identity, "collected_at": now(), "attachments": []}
    if not school.school_code:
        return {**record, "status": "roster_identity_unconfirmed"}
    stage = "lookup_failed"
    try:
        if stop.wait(pause):
            return {**record, "status": "stopped"}
        browser = opener()
        uid, error = resolve_shl_idf(browser, school)
        if not uid:
            if re.search(r"HTTP Error (403|429|503)\b", error):
                stop.set()
            return {**record, "status": stage, "detail": error}
        stage = "page_failed"
        source_url = f"{BASE_URL}{ITEM_PATH}?{urlencode({'SHL_IDF_CD': uid, 'JG_YEAR': year, 'JG_CHASU': round_no})}"
        record["source_url"] = source_url
        meta = post(browser, HANGMOK_URL, {"SHL_IDF_CD": uid}, 15)
        items = [
            item for item in json.loads(meta.body)
            if isinstance(item, dict) and item.get("GS_HANGMOK_NO") == "4-가"
        ]
        if len(items) != 1 or items[0].get("GS_URL") != ITEM_PATH:
            return {**record, "status": stage, "detail": "4ga_item_missing_or_changed"}
        params = params_from_item(items[0], str(year), uid) | {"JG_CHASU": str(round_no)}
        request = ItemRequest(ITEM_PATH, params)
        page = fetch_item_html(browser, request)
        select = ROUND_SELECTOR.search(page.body)
        options = ROUND_OPTION.findall(select[1]) if select else []
        if options != [f"{year}{round_no}"]:
            classification = classify_response_html(int(page.status_code), page.body)
            if classification.result_status == "blocked":
                stop.set()
            return {**record, "status": "round_unconfirmed", "observed_rounds": options,
                    "detail": classification.error_pattern}
        record["confirmed_round"] = options[0]
        attachments = named_attachments(page.body, request)
        if not attachments:
            classification = classify_response_html(int(page.status_code), page.body)
            if classification.result_status == "blocked":
                stop.set()
            status = "no_attachments_reported" if classification.error_pattern == "no_file" else stage
            return {**record, "status": status, "detail": classification.error_pattern or "no_recognized_links"}
        form = DOWNLOAD_FORM.search(page.body)
        download_params = parse_hidden_params(form[1]) if form else {}
        expected = {"SHL_IDF_CD": uid, "JG_YEAR": str(year), "JG_CHASU": str(round_no)}
        if any(download_params.get(key) != value for key, value in expected.items()):
            return {**record, "status": "round_unconfirmed", "detail": "download_form_scope_mismatch"}
        if len({attachment.file_seq for attachment in attachments}) != len(attachments):
            return {**record, "status": stage, "detail": "duplicate_file_sequences"}
        for attachment in attachments:
            filename = attachment.filename
            final_url = f"{BASE_URL}/servlets/EiFileDownLoad.do?{urlencode(download_params | {'FILE_SEQ': attachment.file_seq})}"
            row = {
                **identity, "record_type": "attachment", "candidate_name": filename,
                "file_seq": attachment.file_seq, "source_url": source_url, "final_url": final_url,
                "semester_signal": plan_status(filename), "collected_at": now(),
            }
            record["attachments"].append(row)
            if row["semester_signal"] == "non_plan_filename":
                row["result"] = "excluded_non_plan_filename"
                continue
            if stop.wait(pause):
                row.update(result="failed", failure_reason="paused_after_service_response")
                continue
            try:
                payload = download(browser, final_url)
                validation = classify_download_payload(payload.body, payload.content_type)
                if not validation.is_valid:
                    row.update(result="failed", failure_reason=validation.reason)
                    continue
                digest = hashlib.sha256(payload.body).hexdigest()
                suffix = Path(filename).suffix.lower()
                if validation.detected_type == "pdf":
                    suffix = ".pdf"
                elif suffix not in {".hwp", ".hwpx", ".docx", ".xlsx", ".zip", ".doc", ".xls"}:
                    suffix = ".zip" if validation.detected_type == "zip_office_xml" else ".bin"
                folder = raw / safe_name(school.region_sido) / school.school_code
                target = folder / f"{digest}_{safe_name(Path(filename).stem)[:65]}{suffix}"
                if target.exists():
                    with target.open("rb") as existing:
                        if hashlib.file_digest(existing, "sha256").hexdigest() != digest:
                            raise ValueError("existing_original_hash_mismatch")
                else:
                    atomic_bytes(target, payload.body)
                row.update(result="downloaded", sha256=digest, size_bytes=len(payload.body),
                           saved_path=target.relative_to(project).as_posix(),
                           content_type=payload.content_type, status_detail=validation.detected_type)
            except (OSError, ValueError) as exc:
                if isinstance(exc, HTTPError) and exc.code in {403, 429, 503}:
                    stop.set()
                row.update(result="failed", failure_reason=f"{type(exc).__name__}: {exc}")
        status = "attachment_failed" if any(row["result"] == "failed" for row in record["attachments"]) else "listed"
        return {**record, "status": status}
    except (OSError, ValueError) as exc:
        if isinstance(exc, HTTPError) and exc.code in {403, 429, 503}:
            stop.set()
        return {**record, "status": stage, "detail": f"{type(exc).__name__}: {exc}"}


def save_summary(project: Path, derived: Path, schools: list[School], latest: dict[str, dict]) -> None:
    rows = [row for receipt in latest.values() for row in receipt["attachments"]]
    files = {row["saved_path"]: row for row in rows if row["result"] == "downloaded"}
    statuses = Counter(receipt["status"] for receipt in latest.values())
    mismatches = []
    for name, row in files.items():
        target = project / name
        if not target.is_file() or target.stat().st_size != row["size_bytes"]:
            mismatches.append(name)
    text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    atomic_bytes(derived / "attachments.jsonl", text.encode("utf-8"))
    summary = {
        "updated_at": now(),
        "roster_schools": len(schools), "attempted_schools": len(latest),
        "unattempted_schools": len(schools) - len(latest), "school_statuses": dict(statuses),
        "unconfirmed_schools": sum(statuses[status] for status in RETRYABLE | {"roster_identity_unconfirmed"}),
        "schools_with_downloads": len({row["school_code"] for row in files.values()}),
        "attachment_rows": len(rows), "attachment_statuses": dict(Counter(row["result"] for row in rows)),
        "downloaded_unique_paths": len(files), "unique_content_hashes": len({row["sha256"] for row in files.values()}),
        "duplicate_download_rows_by_path": sum(row["result"] == "downloaded" for row in rows) - len(files),
        "stored_bytes": sum(row["size_bytes"] for row in files.values()),
        "semester_signals": dict(Counter(row["semester_signal"] for row in files.values())),
        "missing_or_size_mismatch_paths": mismatches,
    }
    atomic_json(derived / "collection_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roster", type=Path, required=True)
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--round", type=int, choices=(1, 3), default=3)
    parser.add_argument("--limit", type=int, default=0, help="cap schools attempted in this invocation")
    parser.add_argument("--workers", type=int, choices=(1, 2, 3), default=2)
    parser.add_argument("--pause", type=float, default=0.25)
    parser.add_argument("--retry-failed", action="store_true")
    args = parser.parse_args()
    if not 2024 <= args.year <= 2099 or args.limit < 0 or args.pause < 0.2:
        parser.error("invalid year, limit or pause (minimum 0.2 seconds)")
    project = Path(__file__).resolve().parents[1]
    key = f"{args.year}-round-{args.round}"
    raw = project / "data" / "raw" / "schoolinfo" / "4ga_rounds" / key
    derived = project / "data" / "derived" / "schoolinfo_4ga" / key
    receipts = derived / "school_receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    schools = read_roster(args.roster)
    stop = threading.Event()
    with sqlite3.connect(derived / "collector_lock.sqlite", timeout=0) as lock:
        lock.execute("BEGIN IMMEDIATE")
        snapshot = derived / "roster.csv"
        roster_bytes = args.roster.read_bytes()
        if snapshot.exists() and snapshot.read_bytes() != roster_bytes:
            raise SystemExit("roster differs from the preserved scope of this run")
        if not snapshot.exists():
            atomic_bytes(snapshot, roster_bytes)
        latest = {}
        attempts = {}
        for school in schools:
            code = school.school_id
            previous = sorted(receipts.glob(f"{code}-*.json"))
            attempts[code] = len(previous)
            if previous:
                latest[code] = json.loads(previous[-1].read_text(encoding="utf-8"))
        pending = [
            school for school in schools
            if school.school_id not in latest or (
                args.retry_failed and latest[school.school_id]["status"] in RETRYABLE
            )
        ]
        pending = pending[:args.limit] if args.limit else pending
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for start in range(0, len(pending), args.workers):
                if stop.is_set():
                    break
                batch = pending[start:start + args.workers]
                jobs = [pool.submit(collect_school, school, project, raw, args.year,
                                    args.round, args.pause, stop) for school in batch]
                for job in jobs:
                    result = job.result()
                    code = result["school_id"]
                    atomic_json(receipts / f"{code}-{attempts[code] + 1:04}.json", result)
                    latest[code] = result
                if start % (args.workers * 10) == 0:
                    print(f"processed_this_run={start + len(batch)}/{len(pending)}", flush=True)
        save_summary(project, derived, schools, latest)
        if stop.is_set():
            raise SystemExit("paused after Schoolinfo access restriction or service response")


if __name__ == "__main__":
    main()
