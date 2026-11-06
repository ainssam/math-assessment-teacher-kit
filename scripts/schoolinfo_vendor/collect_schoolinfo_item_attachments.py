# /// script
# requires-python = ">=3.11"
# ///
# ----- How to run -----
#   py -3 analysis/scripts/collect_schoolinfo_item_attachments.py --item 2-라
#   py -3 analysis/scripts/collect_schoolinfo_item_attachments.py --item 2-라 --all
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

from pilot_2ga_http import HANGMOK_URL, ItemRequest, download, fetch_item_html, opener, params_from_item, post, resolve_shl_idf
from schoolinfo_2ga_request_audit import classify_download_payload, classify_response_html, html_title
from schoolinfo_documents_core import BASE_URL, ITEMS, SCHOOLS_PATH, DisclosureItem, School, build_source_url, clean_html_text, extension_from_name, parse_attachments


ROOT: Final = Path(__file__).resolve().parents[2]
ARCHIVE_ROOT: Final = ROOT / "교육과정운영계획"
RAW_ROOT: Final = ARCHIVE_ROOT / "data" / "raw"
NORMALIZED_ROOT: Final = ROOT / "analysis" / "data" / "normalized"
SCHOOLINFO_LOG: Final = NORMALIZED_ROOT / "schoolinfo_item_attachment_download_log.csv"
FILE_ANCHOR_RE: Final = re.compile(r"<a[^>]+class=[\"']file_name[\"'][^>]*>.*?</a>", re.I | re.S)
FILE_SEQ_RE: Final = re.compile(r"getEiFile\d+\('([^']+)'\)")
ITEM_SLUGS: Final = {"2-가": "2ga", "2-라": "2ra", "4-가": "4ga"}
PRIORITY_SCHOOLS: Final = (
    "갈산고등학교",
    "용남고등학교",
    "북일고등학교",
    "충남과학고등학교",
    "공주대학교사범대학부설고등학교",
    "충남삼성고등학교",
    "충남외국어고등학교",
    "배방고등학교",
    "설화고등학교",
    "천안여자고등학교",
    "북일여자고등학교",
)


@dataclass(frozen=True, slots=True)
class RunConfig:
    item_no: str
    sido: str
    year: int
    include_all: bool
    school_names: tuple[str, ...]
    sleep_seconds: float


@dataclass(frozen=True, slots=True)
class DownloadLog:
    item_no: str
    item_name: str
    school_code: str
    school_name: str
    district: str
    file_seq: str
    candidate_name: str
    result: str
    status_detail: str
    saved_path: str
    content_type: str
    size_bytes: int
    source_url: str
    final_url: str
    failure_reason: str


LOG_FIELDS: Final = tuple(DownloadLog.__dataclass_fields__)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def csv_text(row: dict[str, str], field: str) -> str:
    return row.get(field, "").strip()


def safe_name(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", value).strip("_")[:140] or "schoolinfo_attachment"


def display_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def selected_item(item_no: str) -> DisclosureItem:
    matches = [item for item in ITEMS if item.no == item_no]
    if len(matches) != 1:
        raise SystemExit(f"unknown disclosure item: {item_no}")
    return matches[0]


def load_schools(config: RunConfig) -> tuple[School, ...]:
    wanted = set(config.school_names)
    schools: list[School] = []
    with SCHOOLS_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if csv_text(row, "year") != str(config.year) or csv_text(row, "region_sido") != config.sido:
                continue
            school = School(
                school_id=csv_text(row, "school_id"),
                school_name=csv_text(row, "school_name"),
                region_sido=csv_text(row, "region_sido"),
                region_sgg=csv_text(row, "region_sgg"),
                school_code=csv_text(row, "school_code"),
                neis_school_code=csv_text(row, "neis_school_code"),
                education_office_code=csv_text(row, "education_office_code"),
            )
            if config.include_all or school.school_name in wanted:
                schools.append(school)
    return tuple(sorted(schools, key=lambda item: (item.region_sgg, item.school_name)))


def request_for_item(browser: urllib.request.OpenerDirector, shl_idf_cd: str, item: DisclosureItem, year: int) -> ItemRequest | str:
    try:
        result = post(browser, HANGMOK_URL, {"SHL_IDF_CD": shl_idf_cd}, 10)
        payload = json.loads(result.body)
    except (TimeoutError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return f"hangmok_json_failed: {type(exc).__name__}: {exc}"
    matches = [row for row in payload if isinstance(row, dict) and row.get("GS_HANGMOK_NO") == item.no]
    if len(matches) != 1:
        return f"hangmok_json_missing_item: {item.no}"
    found = matches[0]
    disclosure_year = str(found.get("JG_YEAR", year))
    return ItemRequest(str(found.get("GS_URL", item.url_path)), params_from_item(found, disclosure_year, shl_idf_cd))


def original_file_names(item_html: str) -> dict[str, str]:
    names: dict[str, str] = {}
    for anchor in FILE_ANCHOR_RE.findall(item_html):
        match = FILE_SEQ_RE.search(anchor)
        if match is None:
            continue
        label = clean_html_text(anchor)
        names[match.group(1)] = html.unescape(re.sub(r"\([0-9,]+\s*KB\)\s*$", "", label).strip())
    return names


def named_attachments(item_html: str, request: ItemRequest):
    names = original_file_names(item_html)
    ordered = tuple(names.items())
    rows = []
    for index, item in enumerate(parse_attachments(item_html, request.params)):
        fallback_seq, fallback_name = ordered[index] if index < len(ordered) else (item.file_seq, item.filename)
        file_seq = item.file_seq or fallback_seq
        rows.append(replace(item, file_seq=file_seq, filename=names.get(file_seq, fallback_name)))
    return tuple(rows)


def failure_log(item: DisclosureItem, school: School, source_url: str, reason: str) -> DownloadLog:
    return DownloadLog(item.no, item.name, school.school_code, school.school_name, school.region_sgg, "", "", "failed", "", "", "", 0, source_url, source_url, reason)


def store_payload(item: DisclosureItem, school: School, file_name: str, body: bytes) -> tuple[str, str, str]:
    slug = ITEM_SLUGS.get(item.no, safe_name(item.no))
    digest = hashlib.sha256(body).hexdigest()
    suffix = Path(file_name).suffix or ".bin"
    target_dir = RAW_ROOT / slug / school.region_sido / school.school_name
    existing = sorted(target_dir.glob(f"{school.school_code}_{digest[:12]}_*"))
    if existing:
        return digest, display_path(existing[0]), str(existing[0])
    target = target_dir / f"{school.school_code}_{digest[:12]}_{safe_name(Path(file_name).stem)}{suffix}"
    target_dir.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    return digest, display_path(target), str(target)


def attachment_log(browser: urllib.request.OpenerDirector, item: DisclosureItem, school: School, source_url: str, item_html: str, attachment) -> DownloadLog:
    try:
        result = download(browser, attachment.download_url)
    except (TimeoutError, urllib.error.URLError) as exc:
        return failure_log(item, school, attachment.download_url, f"download_failed: {type(exc).__name__}: {exc}")
    validation = classify_download_payload(result.body, result.content_type)
    if not validation.is_valid:
        return failure_log(item, school, attachment.download_url, f"download_validation_failed: {validation.reason}")
    _digest, saved_path, _target = store_payload(item, school, attachment.filename, result.body)
    return DownloadLog(
        item.no,
        item.name,
        school.school_code,
        school.school_name,
        school.region_sgg,
        attachment.file_seq,
        attachment.filename,
        "downloaded",
        validation.detected_type,
        saved_path,
        result.content_type,
        len(result.body),
        source_url,
        attachment.download_url,
        "",
    )


def collect_school(browser: urllib.request.OpenerDirector, item: DisclosureItem, school: School, year: int) -> tuple[DownloadLog, ...]:
    shl_idf_cd, lookup_error = resolve_shl_idf(browser, school)
    source_url = build_source_url(shl_idf_cd, item) if shl_idf_cd else f"{BASE_URL}{item.url_path}"
    if lookup_error:
        return (failure_log(item, school, source_url, lookup_error),)
    request = request_for_item(browser, shl_idf_cd, item, year)
    if isinstance(request, str):
        return (failure_log(item, school, source_url, request),)
    try:
        html_result = fetch_item_html(browser, request)
    except (TimeoutError, urllib.error.URLError) as exc:
        return (failure_log(item, school, source_url, f"item_fetch_failed: {type(exc).__name__}: {exc}"),)
    attachments = named_attachments(html_result.body, request)
    if not attachments:
        classification = classify_response_html(int(html_result.status_code or "0"), html_result.body)
        reason = classification.error_pattern or f"no_attachment: {html_title(html_result.body)}"
        return (failure_log(item, school, source_url, reason),)
    return tuple(attachment_log(browser, item, school, source_url, html_result.body, attachment) for attachment in attachments)


def write_log(rows: tuple[DownloadLog, ...]) -> None:
    NORMALIZED_ROOT.mkdir(parents=True, exist_ok=True)
    existing: list[dict[str, str]] = []
    if SCHOOLINFO_LOG.is_file():
        with SCHOOLINFO_LOG.open("r", encoding="utf-8-sig", newline="") as handle:
            existing = list(csv.DictReader(handle))
    merged: dict[tuple[str, str, str, str], dict[str, str | int]] = {}
    for row in existing:
        normalized = {field: row.get(field, "") for field in LOG_FIELDS}
        key = (
            str(normalized["item_no"]),
            str(normalized["school_code"]),
            str(normalized["file_seq"]),
            str(normalized["candidate_name"]),
        )
        merged[key] = normalized
    for row in rows:
        normalized = asdict(row)
        key = (row.item_no, row.school_code, row.file_seq, row.candidate_name)
        merged[key] = normalized
    with SCHOOLINFO_LOG.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_FIELDS)
        writer.writeheader()
        writer.writerows(
            merged[key]
            for key in sorted(merged, key=lambda item: (item[0], item[1], item[2], item[3]))
        )


def parse_args() -> RunConfig:
    parser = argparse.ArgumentParser(description="Download Schoolinfo disclosure item attachments.")
    parser.add_argument("--item", default="2-라")
    parser.add_argument("--sido", default="충청남도")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--school", action="append", default=[])
    parser.add_argument("--sleep-seconds", type=float, default=0.8)
    args = parser.parse_args()
    schools = tuple(args.school) if args.school else PRIORITY_SCHOOLS
    return RunConfig(args.item, args.sido, args.year, bool(args.all), schools, args.sleep_seconds)


def main() -> int:
    config = parse_args()
    item = selected_item(config.item_no)
    schools = load_schools(config)
    browser = opener()
    rows: list[DownloadLog] = []
    for school in schools:
        rows.extend(collect_school(browser, item, school, config.year))
        time.sleep(config.sleep_seconds)
    result = tuple(rows)
    write_log(result)
    downloaded = sum(1 for row in result if row.result == "downloaded")
    print(f"OK item: {item.no} {item.name}")
    print(f"OK schools: {len(schools)}")
    print(f"OK rows: {len(result)} downloaded={downloaded}")
    print(f"OK log: {SCHOOLINFO_LOG.relative_to(ROOT)}")
    print(f"OK collected_at: {now_iso()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

