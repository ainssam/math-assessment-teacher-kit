from __future__ import annotations

import html
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from typing import Final

from schoolinfo_documents_core import BASE_URL, USER_AGENT


TITLE_RE: Final = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
HTML_PREFIXES: Final = (b"<!doctype html", b"<html", b"\xef\xbb\xbf<!doctype html", b"\xef\xbb\xbf<html")
ZIP_MAGIC: Final = b"PK\x03\x04"
OLE_MAGIC: Final = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
PDF_MAGIC: Final = b"%PDF-"
RETRY_STATUS_CODES: Final = (429, 403, 503)


@dataclass(frozen=True, slots=True)
class ResponseClassification:
    error_pattern: str
    result_status: str


@dataclass(frozen=True, slots=True)
class AuditContext:
    school_code: str
    school_name: str
    sido: str
    target_year: int
    source_url: str


@dataclass(frozen=True, slots=True)
class AuditRow:
    school_code: str
    school_name: str
    sido: str
    target_year: int
    source_url: str
    request_method: str
    status_code: str
    final_url: str
    content_type: str
    response_size: int
    html_title: str
    error_pattern: str
    retry_count: int
    result_status: str


@dataclass(frozen=True, slots=True)
class FetchResult:
    body: str
    status_code: str
    final_url: str
    content_type: str
    retry_count: int
    error_pattern: str
    result_status: str


@dataclass(frozen=True, slots=True)
class DownloadValidation:
    is_valid: bool
    detected_type: str
    reason: str


def html_title(item_html: str) -> str:
    match = TITLE_RE.search(item_html)
    if match is None:
        return ""
    return html.unescape(re.sub(r"\s+", " ", match.group(1))).strip()


def classify_response_html(status_code: int, item_html: str) -> ResponseClassification:
    lowered = item_html.lower()
    if status_code == 403 or "접근이 제한" in item_html or "권한" in item_html or "forbidden" in lowered:
        return ResponseClassification("access_restriction", "blocked")
    if status_code in (429, 503) or "서비스 일시 중단" in item_html or "wrap_error" in item_html or "maintenance" in lowered:
        return ResponseClassification("service_interruption", "blocked")
    if "선택하신 년도" in item_html or "조회할 수 없습니다" in item_html or "invalid year" in lowered:
        return ResponseClassification("invalid_year", "failed")
    if "첨부파일이 없습니다" in item_html or "등록된 파일이 없습니다" in item_html or "자료가 없습니다" in item_html:
        return ResponseClassification("no_file", "missing")
    if "EiFileDownLoad" in item_html and "EiFileDownLoad.do" not in item_html:
        return ResponseClassification("parsing_failure", "failed")
    return ResponseClassification("", "")


def classify_download_payload(payload: bytes, content_type: str) -> DownloadValidation:
    prefix = payload[:32].lstrip().lower()
    lowered_type = content_type.lower()
    if lowered_type.startswith("text/html") or any(prefix.startswith(marker) for marker in HTML_PREFIXES):
        return DownloadValidation(False, "html", "html_response_not_document")
    if payload.startswith(PDF_MAGIC):
        return DownloadValidation(True, "pdf", "")
    if payload.startswith(ZIP_MAGIC):
        return DownloadValidation(True, "zip_office_xml", "")
    if payload.startswith(OLE_MAGIC):
        return DownloadValidation(True, "ole_hwp_or_office", "")
    if "pdf" in lowered_type:
        return DownloadValidation(False, "unknown", "content_type_pdf_without_pdf_magic")
    return DownloadValidation(False, "unknown", "unsupported_or_unknown_document_magic")


def audit_row(context: AuditContext, result: FetchResult) -> AuditRow:
    return AuditRow(
        school_code=context.school_code,
        school_name=context.school_name,
        sido=context.sido,
        target_year=context.target_year,
        source_url=context.source_url,
        request_method="GET" if result.status_code else "NONE",
        status_code=result.status_code,
        final_url=result.final_url,
        content_type=result.content_type,
        response_size=len(result.body.encode("utf-8")),
        html_title=html_title(result.body),
        error_pattern=result.error_pattern,
        retry_count=result.retry_count,
        result_status=result.result_status,
    )


def cached_audit_row(row: AuditRow, result_status: str, error_pattern: str) -> AuditRow:
    return replace(row, request_method="CACHE", result_status=result_status, error_pattern=error_pattern)


def no_request_result(source_url: str, error_pattern: str, result_status: str) -> FetchResult:
    return FetchResult(
        body="",
        status_code="",
        final_url=source_url,
        content_type="",
        retry_count=0,
        error_pattern=error_pattern,
        result_status=result_status,
    )


def fetch_text_with_audit(url: str, data: dict[str, str], timeout: int) -> FetchResult:
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    retry_count = 0
    last_result = no_request_result(url, "live_fetch_failed", "failed")
    for attempt in range(4):
        if attempt:
            retry_count = attempt
            time.sleep(random.uniform(1.5, 4.0) * attempt)
        request = urllib.request.Request(url, data=encoded, headers={"User-Agent": USER_AGENT, "Referer": BASE_URL})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body_bytes = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
                body = body_bytes.decode(charset, errors="replace")
                status_code = response.status
                classification = classify_response_html(status_code, body)
                last_result = FetchResult(
                    body=body,
                    status_code=str(status_code),
                    final_url=response.geturl(),
                    content_type=response.headers.get("Content-Type", ""),
                    retry_count=retry_count,
                    error_pattern=classification.error_pattern,
                    result_status=classification.result_status,
                )
                if status_code not in RETRY_STATUS_CODES and classification.error_pattern != "service_interruption":
                    return last_result
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(exc.headers.get_content_charset() or "utf-8", errors="replace")
            classification = classify_response_html(exc.code, body)
            last_result = FetchResult(
                body=body,
                status_code=str(exc.code),
                final_url=exc.geturl(),
                content_type=exc.headers.get("Content-Type", ""),
                retry_count=retry_count,
                error_pattern=classification.error_pattern,
                result_status=classification.result_status or "failed",
            )
        if retry_count >= 3 or (last_result.error_pattern != "service_interruption" and int(last_result.status_code or "0") not in RETRY_STATUS_CODES):
            return last_result
    return last_result

