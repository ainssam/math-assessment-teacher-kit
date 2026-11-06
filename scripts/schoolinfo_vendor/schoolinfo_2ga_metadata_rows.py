from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Final

from schoolinfo_documents_core import (
    BASE_URL,
    ITEMS,
    DisclosureItem,
    School,
    build_source_url,
    digest_text,
    extension_from_name,
    parse_attachments,
)
from schoolinfo_2ga_request_audit import classify_response_html


ITEM_2GA: Final = ITEMS[0]
METADATA_FIELDS: Final = (
    "metadata_id",
    "school_id",
    "school_code",
    "school_name",
    "sido",
    "source_type",
    "source_url",
    "schoolinfo_item_no",
    "schoolinfo_item_code",
    "shl_idf_cd",
    "collection_date",
    "status",
    "file_name",
    "file_ext",
    "file_seq",
    "download_url",
    "download_params_json",
    "failure_reason",
)


@dataclass(frozen=True, slots=True)
class MetadataRow:
    metadata_id: str
    school_id: str
    school_code: str
    school_name: str
    sido: str
    source_type: str
    source_url: str
    schoolinfo_item_no: str
    schoolinfo_item_code: str
    shl_idf_cd: str
    collection_date: str
    status: str
    file_name: str
    file_ext: str
    file_seq: str
    download_url: str
    download_params_json: str
    failure_reason: str


def metadata_id(school: School, item: DisclosureItem, file_seq: str, status: str, file_name: str) -> str:
    return f"schoolinfo-2ga-meta-{digest_text(f'{school.school_id}:{item.code}:{file_seq}:{status}:{file_name}')}"


def item_params_for_year(school: School, shl_idf_cd: str, item: DisclosureItem, year: int) -> dict[str, str]:
    return {
        "GS_HANGMOK_CD": item.code,
        "GS_HANGMOK_NO": item.no,
        "GS_HANGMOK_NM": item.name,
        "GS_BURYU_CD": item.gs_buryu_cd,
        "JG_BURYU_CD": item.jg_buryu_cd,
        "JG_HANGMOK_CD": item.jg_hangmok_cd,
        "JG_GUBUN": item.jg_gubun,
        "JG_YEAR2": str(year),
        "HG_NM": school.school_name,
        "SHL_IDF_CD": shl_idf_cd,
        "GS_TYPE": "Y",
        "JG_YEAR": str(year),
        "SORT": "BR",
        "CHOSEN_JG_YEAR": str(year),
    }


def empty_row(school: School, item: DisclosureItem, shl_idf_cd: str, status: str, reason: str, collected_at: str) -> MetadataRow:
    source_url = build_source_url(shl_idf_cd, item) if shl_idf_cd else f"{BASE_URL}{item.url_path}"
    return MetadataRow(
        metadata_id=metadata_id(school, item, "", status, ""),
        school_id=school.school_id,
        school_code=school.school_code,
        school_name=school.school_name,
        sido=school.region_sido,
        source_type="schoolinfo_2ga",
        source_url=source_url,
        schoolinfo_item_no=item.no,
        schoolinfo_item_code=item.code,
        shl_idf_cd=shl_idf_cd,
        collection_date=collected_at,
        status=status,
        file_name="",
        file_ext="",
        file_seq="",
        download_url="",
        download_params_json="",
        failure_reason=reason,
    )


def rows_from_html(school: School, shl_idf_cd: str, item_html: str, collected_at: str, year: int) -> tuple[MetadataRow, ...]:
    classification = classify_response_html(200, item_html)
    if classification.error_pattern == "service_interruption":
        reason = "service_interruption: Schoolinfo returned service-interruption or maintenance HTML"
        return (empty_row(school, ITEM_2GA, shl_idf_cd, "blocked", reason, collected_at),)
    if classification.error_pattern == "access_restriction":
        reason = "access_restriction: Schoolinfo returned access-restricted HTML"
        return (empty_row(school, ITEM_2GA, shl_idf_cd, "blocked", reason, collected_at),)
    if classification.error_pattern == "invalid_year":
        reason = "invalid_year: Schoolinfo page rejected the requested target year"
        return (empty_row(school, ITEM_2GA, shl_idf_cd, "failed", reason, collected_at),)
    if classification.error_pattern == "parsing_failure":
        reason = "parsing_failure: Schoolinfo attachment markup was present but could not be parsed"
        return (empty_row(school, ITEM_2GA, shl_idf_cd, "failed", reason, collected_at),)
    if classification.error_pattern == "no_file":
        reason = "no_file: 2-ga item page explicitly reported no attachment"
        return (empty_row(school, ITEM_2GA, shl_idf_cd, "missing", reason, collected_at),)
    attachments = parse_attachments(item_html, item_params_for_year(school, shl_idf_cd, ITEM_2GA, year))
    if not attachments:
        reason = "parsing_failure: 2-ga item page parsed but no file link was found"
        return (empty_row(school, ITEM_2GA, shl_idf_cd, "failed", reason, collected_at),)
    rows: list[MetadataRow] = []
    for attachment in attachments:
        base = empty_row(school, ITEM_2GA, shl_idf_cd, "found", "", collected_at)
        rows.append(
            replace(
                base,
                metadata_id=metadata_id(school, ITEM_2GA, attachment.file_seq, "found", attachment.filename),
                file_name=attachment.filename,
                file_ext=extension_from_name(attachment.filename),
                file_seq=attachment.file_seq,
                download_url=attachment.download_url,
                download_params_json=json.dumps(attachment.params, ensure_ascii=False, sort_keys=True),
            )
        )
    return tuple(rows)

