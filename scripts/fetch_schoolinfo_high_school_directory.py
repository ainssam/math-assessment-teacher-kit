"""Preserve the current Schoolinfo school directory for roster reconciliation."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

from collect_schoolinfo_4ga_historical import atomic_bytes, atomic_json, now

sys.path.insert(0, str(Path(__file__).resolve().parent / "schoolinfo_vendor"))
from pilot_2ga_http import SEARCH_PAGE_URL, opener, post  # noqa: E402
from schoolinfo_documents_core import BASE_URL  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = "/ei/ss/pneiss_a03_s0_school_json.do"
REGION = re.compile(r'<input\b[^>]*\bname="level2"\s+value="(\d{10})"')
FIELDS = (
    "SHL_IDF_CD", "SHL_CD", "SHL_NM", "SHL_KND_SC_CD", "HSH_KND_SC_CD",
    "LCTN_NM", "ADDR_CD_ID", "ADDR_CN", "SHL_ROAD_NM_ADDR", "HMPG_ADDR",
    "FNDN_SC_CD", "CTE_CDDC_CD", "CTE_DSTRT_OFCDC_CD",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--school-kind", choices=("high", "other"), default="high")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9-]+", args.snapshot):
        parser.error("invalid snapshot name")
    kind = "04" if args.school_kind == "high" else "05"
    snapshot = args.snapshot if kind == "04" else f"{args.snapshot}-other"
    raw = ROOT / "data" / "raw" / "schoolinfo" / "rosters" / snapshot
    output = ROOT / "data" / "derived" / "schoolinfo_4ga" / "rosters" / snapshot
    raw.mkdir(parents=True, exist_ok=False)
    output.mkdir(parents=True, exist_ok=False)
    browser = opener()
    with browser.open(SEARCH_PAGE_URL, timeout=15) as response:
        page_bytes = response.read()
        page = page_bytes.decode(response.headers.get_content_charset() or "euc-kr", errors="replace")
    atomic_bytes(raw / "directory_page.html", page_bytes)
    codes = list(dict.fromkeys(REGION.findall(page)))
    if len(codes) < 15:
        raise SystemExit("the official directory's province selector could not be verified")
    rows = []
    source_records = []
    for code in codes:
        time.sleep(0.4)
        response = post(browser, BASE_URL + DIRECTORY, {
            "HG_JONGRYU_GB": kind, "SIDO_CODE": code, "GUGUN_CODE": "",
        }, 20)
        response_bytes = response.body.encode("utf-8")
        target = raw / f"region-{code}.json"
        atomic_bytes(target, response_bytes)
        page_rows = json.loads(response.body)
        if not isinstance(page_rows, list) or not page_rows or any(
            not isinstance(row, dict) or (kind == "04" and row.get("SHL_KND_SC_CD") != kind)
            or not re.fullmatch(r"[0-9a-fA-F-]{36}", str(row.get("SHL_IDF_CD", "")))
            for row in page_rows
        ):
            raise SystemExit(f"invalid school directory response for region {code}")
        source_records.append({
            "region_selector": code, "rows": len(page_rows),
            "sha256": hashlib.sha256(response_bytes).hexdigest(),
            "saved_path": target.relative_to(ROOT).as_posix(),
        })
        rows.extend({"region_selector": code, **{field: row.get(field, "") for field in FIELDS}}
                    for row in page_rows)
        print(f"province={code} schools={len(page_rows)}", flush=True)
    counts = Counter(row["SHL_IDF_CD"] for row in rows)
    duplicate_ids = sorted(uid for uid, count in counts.items() if count > 1)
    if duplicate_ids:
        raise SystemExit(f"directory returned {len(duplicate_ids)} duplicate Schoolinfo IDs")
    csv_text = io.StringIO(newline="")
    writer = csv.DictWriter(csv_text, fieldnames=("region_selector", *FIELDS))
    writer.writeheader()
    writer.writerows(rows)
    filename = "schoolinfo_high_school_directory.csv" if kind == "04" else "schoolinfo_other_school_directory.csv"
    atomic_bytes(output / filename, csv_text.getvalue().encode("utf-8-sig"))
    atomic_json(output / "directory_summary.json", {
        "collected_at": now(), "source_url": SEARCH_PAGE_URL, "endpoint": BASE_URL + DIRECTORY,
        "school_kind_selector": kind, "province_selectors": len(codes), "schools": len(counts),
        "school_kind_counts": dict(Counter(row["SHL_KND_SC_CD"] for row in rows)),
        "duplicate_schoolinfo_ids": len(duplicate_ids), "sources": source_records,
    })


if __name__ == "__main__":
    main()
