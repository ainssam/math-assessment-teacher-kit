# /// script
# requires-python = ">=3.11"
# ///
from __future__ import annotations

import csv
import hashlib
import html
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, TypeAlias


JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

ROOT: Final = Path(__file__).resolve().parents[2]
SCHOOLS_PATH: Final = ROOT / "analysis" / "data" / "normalized" / "schools.csv"
RAW_ROOT: Final = ROOT / "analysis" / "data" / "raw" / "schoolinfo_documents"
NORMALIZED_ROOT: Final = ROOT / "analysis" / "data" / "normalized"
DOCUMENTS_CSV: Final = NORMALIZED_ROOT / "documents.csv"
DOCUMENTS_JSON: Final = NORMALIZED_ROOT / "documents.json"
ACTIVE_YEAR: Final = 2026
BASE_URL: Final = "https://www.schoolinfo.go.kr"
USER_AGENT: Final = "Mozilla/5.0 Task5DocumentDiscovery/0.1"
SERVICE_BLOCK_MARKERS: Final = ("서비스 일시 중단", "wrap_error", "schoolinfo@keris.or.kr")
EXCLUDED_TERMS: Final = ("방과후", "상담", "안전교육", "자유학기제")
UUID_RE: Final = re.compile(r"SHL_IDF_CD=([0-9a-fA-F-]{36})")
INPUT_RE: Final = re.compile(r"<input[^>]+name=[\"']([^\"']+)[\"'][^>]*value=[\"']([^\"']*)[\"']", re.I)
DOWNLOAD_RE: Final = re.compile(r"(?:href|action)=[\"']([^\"']*EiFileDownLoad\.do[^\"']*)[\"']", re.I)
LINK_TEXT_RE: Final = re.compile(r"<a[^>]+(?:href|onclick)=[\"'][^\"']*EiFileDownLoad\.do[^\"']*[\"'][^>]*>(.*?)</a>", re.I | re.S)
FILE_LINK_RE: Final = re.compile(r"<a\b[^>]*class=[\"'][^\"']*\bfile_name\b[^\"']*[\"'][^>]*>.*?</a>", re.I | re.S)
ONCLICK_SEQ_RE: Final = re.compile(r"getEiFile\d+\('([^']+)'\)")
SIZE_SUFFIX_RE: Final = re.compile(r"\([0-9,]+\s*KB\)\s*$")


@dataclass(frozen=True, slots=True)
class School:
    school_id: str
    school_name: str
    region_sido: str
    region_sgg: str
    school_code: str
    neis_school_code: str
    education_office_code: str


@dataclass(frozen=True, slots=True)
class DisclosureItem:
    code: str
    no: str
    name: str
    url_path: str
    gs_buryu_cd: str
    jg_buryu_cd: str
    jg_hangmok_cd: str
    jg_gubun: str
    source_type: str


@dataclass(frozen=True, slots=True)
class Attachment:
    file_seq: str
    filename: str
    download_url: str
    preview_url: str
    params: dict[str, str]


@dataclass(frozen=True, slots=True)
class DocumentRow:
    document_id: str
    source_id: str
    school_id: str
    year: int
    source_type: str
    title: str
    url_or_path: str
    file_type: str
    text_extraction_status: str
    text_length: int
    content_hash: str
    page_count: int
    failure_reason: str
    school_name: str
    region_sido: str
    region_sgg: str
    item_code: str
    item_name: str
    disclosure_no: str
    shl_idf_cd: str
    file_seq: str
    original_filename: str
    content_type: str
    size_bytes: int
    storage_backend: str
    local_path: str
    drive_file_id: str
    drive_url: str
    sha256: str
    byte_size: int
    retention_policy: str
    extraction_cache_path: str
    download_status: str
    collection_status: str
    source_url: str
    preview_url: str
    raw_html_path: str
    downloaded_path: str


ITEMS: Final = (
    DisclosureItem("14", "2-가", "학교교육과정 편성ㆍ운영 및 평가에 관한 사항", "/ei/pp/Pneipp_b14_s0p.do", "JG100", "JG020", "05", "1", "education_plan"),
    DisclosureItem("20", "2-라", "교육운영 특색사업 계획", "/ei/pp/Pneipp_b20_s0p.do", "JG130", "JG020", "67", "1", "schoolinfo_disclosure"),
    DisclosureItem("43", "4-가", "교과별(학년별) 교수ㆍ학습 및 평가계획에 관한 사항", "/ei/pp/Pneipp_b43_s0p.do", "JG110", "JG040", "14", "1", "evaluation_plan"),
)
DOCUMENT_FIELDS: Final = tuple(DocumentRow.__dataclass_fields__)


class DocumentDiscoveryError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def digest_text(value: str, length: int = 16) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def clean_html_text(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", value)).strip()


def text(row: dict[str, str], field: str) -> str:
    return row.get(field, "").strip()


def load_schools() -> tuple[School, ...]:
    with SCHOOLS_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [
            School(
                school_id=text(row, "school_id"),
                school_name=text(row, "school_name"),
                region_sido=text(row, "region_sido"),
                region_sgg=text(row, "region_sgg"),
                school_code=text(row, "school_code"),
                neis_school_code=text(row, "neis_school_code"),
                education_office_code=text(row, "education_office_code"),
            )
            for row in csv.DictReader(handle)
            if text(row, "year") == str(ACTIVE_YEAR)
        ]
    if not rows:
        raise DocumentDiscoveryError(f"missing 2026 schools in {SCHOOLS_PATH.relative_to(ROOT)}")
    return tuple(sorted(rows, key=lambda item: (item.region_sido, item.region_sgg, item.school_name, item.school_id)))


def stratified_sample(schools: tuple[School, ...], limit: int) -> tuple[School, ...]:
    by_region: dict[str, list[School]] = {}
    for school in schools:
        by_region.setdefault(school.region_sido, []).append(school)
    selected: list[School] = []
    round_index = 0
    while len(selected) < limit:
        changed = False
        for region in sorted(by_region):
            region_schools = by_region[region]
            if round_index < len(region_schools) and len(selected) < limit:
                selected.append(region_schools[round_index])
                changed = True
        if not changed:
            break
        round_index += 1
    return tuple(selected)


def school_from_detail(detail_html: str, schools: tuple[School, ...]) -> tuple[School | None, str]:
    uuid_match = UUID_RE.search(detail_html)
    school_code = next(iter(re.findall(r'var sdSchulCode = "([^"]+)"', detail_html)), "")
    office_code = next(iter(re.findall(r"sidoScCode = '([^']+)'", detail_html)), "")
    for school in schools:
        if school.neis_school_code == school_code and (not office_code or school.education_office_code == office_code):
            return school, uuid_match.group(1) if uuid_match else ""
    return None, uuid_match.group(1) if uuid_match else ""


def parse_hidden_params(item_html: str) -> dict[str, str]:
    return {name: html.unescape(value) for name, value in INPUT_RE.findall(item_html)}


def item_params(school: School, shl_idf_cd: str, item: DisclosureItem) -> dict[str, str]:
    return {
        "GS_HANGMOK_CD": item.code,
        "GS_HANGMOK_NO": item.no,
        "GS_HANGMOK_NM": item.name,
        "GS_BURYU_CD": item.gs_buryu_cd,
        "JG_BURYU_CD": item.jg_buryu_cd,
        "JG_HANGMOK_CD": item.jg_hangmok_cd,
        "JG_GUBUN": item.jg_gubun,
        "JG_YEAR2": str(ACTIVE_YEAR),
        "HG_NM": school.school_name,
        "SHL_IDF_CD": shl_idf_cd,
        "GS_TYPE": "Y",
        "JG_YEAR": str(ACTIVE_YEAR),
        "SORT": "BR",
        "CHOSEN_JG_YEAR": str(ACTIVE_YEAR),
    }


def is_blocked_html(item_html: str) -> bool:
    return any(marker in item_html for marker in SERVICE_BLOCK_MARKERS)


def parse_attachments(item_html: str, defaults: dict[str, str]) -> tuple[Attachment, ...]:
    hidden = defaults | parse_hidden_params(item_html)
    link_texts = [clean_html_text(value) for value in LINK_TEXT_RE.findall(item_html)]
    attachments: list[Attachment] = []
    seen_file_seq: set[str] = set()

    for anchor in FILE_LINK_RE.findall(item_html):
        seq_match = ONCLICK_SEQ_RE.search(anchor)
        if seq_match is None:
            continue
        file_seq = seq_match.group(1)
        filename = SIZE_SUFFIX_RE.sub("", clean_html_text(anchor)).strip() or f"schoolinfo_attachment_{file_seq}"
        params = hidden | {"FILE_SEQ": file_seq}
        query_text = urllib.parse.urlencode(params)
        download_url = f"{BASE_URL}/servlets/EiFileDownLoad.do?{query_text}"
        preview_url = f"{BASE_URL}/pn/cm/documentView.do?PREVIEW_TYPE=GONGSI&{query_text}"
        attachments.append(Attachment(file_seq=file_seq, filename=filename, download_url=download_url, preview_url=preview_url, params=params))
        seen_file_seq.add(file_seq)

    for index, raw_url in enumerate(DOWNLOAD_RE.findall(item_html)):
        decoded_url = html.unescape(raw_url)
        absolute = urllib.parse.urljoin(BASE_URL, decoded_url)
        parsed = urllib.parse.urlparse(absolute)
        query = {key: values[-1] for key, values in urllib.parse.parse_qs(parsed.query).items()}
        params = hidden | query
        file_seq = params.get("FILE_SEQ") or str(index + 1)
        if file_seq in seen_file_seq or (not parsed.query and not params.get("FILE_SEQ")):
            continue
        filename = link_texts[index] if index < len(link_texts) and link_texts[index] else f"schoolinfo_attachment_{file_seq}"
        query_text = urllib.parse.urlencode(params)
        download_url = f"{BASE_URL}/servlets/EiFileDownLoad.do?{query_text}"
        preview_url = f"{BASE_URL}/pn/cm/documentView.do?PREVIEW_TYPE=GONGSI&{query_text}"
        attachments.append(Attachment(file_seq=file_seq, filename=filename, download_url=download_url, preview_url=preview_url, params=params))
        seen_file_seq.add(file_seq)
    return tuple(attachments)


def extension_from_name(filename: str) -> str:
    suffix = Path(filename).suffix.lower().lstrip(".")
    return suffix if suffix else "unknown"


def build_source_url(shl_idf_cd: str, item: DisclosureItem) -> str:
    return f"{BASE_URL}{item.url_path}?SHL_IDF_CD={urllib.parse.quote(shl_idf_cd)}"


def fetch_text(url: str, data: dict[str, str] | None, timeout: int = 20) -> str:
    encoded = urllib.parse.urlencode(data).encode("utf-8") if data is not None else None
    request = urllib.request.Request(url, data=encoded, headers={"User-Agent": USER_AGENT, "Referer": BASE_URL})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
    return body.decode(charset, errors="replace")


def fetch_bytes(url: str, timeout: int = 30) -> tuple[bytes, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Referer": BASE_URL})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(), response.headers.get("Content-Type", "")


def raw_html_path(school: School, item: DisclosureItem) -> Path:
    return RAW_ROOT / "html" / str(ACTIVE_YEAR) / school.school_id / f"{item.code}.html"


def attachment_path(school: School, item: DisclosureItem, attachment: Attachment) -> Path:
    safe_name = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", attachment.filename)[:120]
    suffix = Path(safe_name).suffix
    filename = safe_name if suffix else f"{safe_name}.{extension_from_name(attachment.filename)}"
    return RAW_ROOT / "files" / str(ACTIVE_YEAR) / school.school_id / item.code / filename

