from __future__ import annotations

import http.cookiejar
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Final

from schoolinfo_2ga_metadata_rows import ITEM_2GA
from schoolinfo_documents_core import BASE_URL, USER_AGENT, School


SEARCH_URL: Final = f"{BASE_URL}/ei/ss/pneiss_a04_s0/getSchoolList.do"
SEARCH_PAGE_URL: Final = f"{BASE_URL}/ei/ss/pneiss_a03_s0.do"
HANGMOK_URL: Final = f"{BASE_URL}/ei/ss/pneiss_a03_s0_hangmok_json.do"


@dataclass(frozen=True, slots=True)
class FetchHtmlResult:
    body: str
    status_code: str
    content_type: str
    final_url: str


@dataclass(frozen=True, slots=True)
class DownloadResult:
    body: bytes
    content_type: str


@dataclass(frozen=True, slots=True)
class ItemRequest:
    path: str
    params: dict[str, str]


def opener() -> urllib.request.OpenerDirector:
    jar = http.cookiejar.CookieJar()
    browser = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    browser.open(urllib.request.Request(SEARCH_PAGE_URL, headers={"User-Agent": USER_AGENT}), timeout=10).read()
    return browser


def post(opener_value: urllib.request.OpenerDirector, url: str, data: dict[str, str], timeout: int) -> FetchHtmlResult:
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=encoded,
        headers={
            "User-Agent": USER_AGENT,
            "Referer": SEARCH_PAGE_URL,
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        },
    )
    with opener_value.open(request, timeout=timeout) as response:
        body = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        return FetchHtmlResult(
            body.decode(charset, errors="replace"),
            str(response.status),
            response.headers.get("Content-Type", ""),
            response.geturl(),
        )


def post_with_retry(
    opener_value: urllib.request.OpenerDirector,
    url: str,
    data: dict[str, str],
    timeout: int,
    attempts: int = 2,
    sleep_seconds: float = 0.8,
) -> FetchHtmlResult:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return post(opener_value, url, data, timeout)
        except (TimeoutError, urllib.error.URLError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt + 1 == attempts:
                raise
            time.sleep(sleep_seconds)
    assert last_error is not None
    raise last_error


def resolve_shl_idf(opener_value: urllib.request.OpenerDirector, school: School) -> tuple[str, str]:
    try:
        result = post_with_retry(opener_value, SEARCH_URL, {"SEARCH_WORD": school.school_name}, 10)
        payload = json.loads(result.body)
    except (TimeoutError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return "", f"school_search_failed: {type(exc).__name__}: {exc}"
    matches = [
        item for item in payload
        if isinstance(item, dict) and item.get("SHL_NM") == school.school_name and item.get("SCHUL_KIND") == "04"
    ]
    if not matches:
        return "", "school_search_no_match: Schoolinfo autocomplete returned no exact high-school match"
    if len(matches) > 1:
        office_prefix = school.education_office_code[:1].upper()
        office_matches = [
            item
            for item in matches
            if office_prefix and str(item.get("SHL_CD", "")).upper().startswith(office_prefix)
        ]
        if office_matches:
            matches = office_matches
    if len(matches) > 1:
        region_matches = [
            item
            for item in matches
            if str(item.get("USER_DFN_CODE_VALUE_01", "")) == school.region_sido
        ]
        if region_matches:
            matches = region_matches
    if len(matches) != 1:
        return "", "school_search_ambiguous: Schoolinfo autocomplete returned multiple exact matches"
    shl_idf_cd = str(matches[0].get("SHL_IDF_CD", "")).strip()
    return shl_idf_cd, "" if shl_idf_cd else "school_search_missing_shl_idf_cd"


def item_request(opener_value: urllib.request.OpenerDirector, shl_idf_cd: str, year: int) -> ItemRequest | str:
    try:
        result = post_with_retry(opener_value, HANGMOK_URL, {"SHL_IDF_CD": shl_idf_cd}, 10)
        payload = json.loads(result.body)
    except (TimeoutError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return f"hangmok_json_failed: {type(exc).__name__}: {exc}"
    matches = [item for item in payload if isinstance(item, dict) and item.get("GS_HANGMOK_NO") == ITEM_2GA.no]
    if len(matches) != 1:
        return "hangmok_json_missing_2ga: Schoolinfo returned no unique 2-ga item"
    item = matches[0]
    disclosure_year = str(item.get("JG_YEAR", year))
    return ItemRequest(str(item.get("GS_URL", ITEM_2GA.url_path)), params_from_item(item, disclosure_year, shl_idf_cd))


def params_from_item(item: dict, disclosure_year: str, shl_idf_cd: str) -> dict[str, str]:
    return {
        "GS_HANGMOK_CD": str(item.get("GS_HANGMOK_CD", "")),
        "GS_HANGMOK_NO": str(item.get("GS_HANGMOK_NO", "")),
        "GS_HANGMOK_NM": str(item.get("GS_HANGMOK_NM", "")),
        "GS_BURYU_CD": str(item.get("GS_BURYU_CD", "")),
        "JG_BURYU_CD": str(item.get("JG_BURYU_CD", "")),
        "JG_HANGMOK_CD": str(item.get("JG_HANGMOK_CD", "")),
        "JG_GUBUN": str(item.get("JG_GUBUN", "")),
        "JG_YEAR2": disclosure_year,
        "SHL_IDF_CD": shl_idf_cd,
        "GS_TYPE": "Y",
        "JG_YEAR": disclosure_year,
        "CHOSEN_JG_YEAR": disclosure_year,
        "PRE_JG_YEAR": disclosure_year,
    }


def fetch_item_html(opener_value: urllib.request.OpenerDirector, request: ItemRequest) -> FetchHtmlResult:
    return post(opener_value, f"{BASE_URL}{request.path}", request.params, 15)


def download(opener_value: urllib.request.OpenerDirector, url: str) -> DownloadResult:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Referer": BASE_URL})
    with opener_value.open(request, timeout=30) as response:
        return DownloadResult(response.read(), response.headers.get("Content-Type", ""))

