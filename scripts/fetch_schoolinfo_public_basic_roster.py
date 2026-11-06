"""Preserve public Schoolinfo basic records by year and education office."""

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
from pilot_2ga_http import opener, post  # noqa: E402
from schoolinfo_documents_core import BASE_URL  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
SOURCE = BASE_URL + "/ng/go/pnnggo_a01_l2.do"
FIELDS = ("SHL_IDF_CD", "SCHUL_CODE", "SCHUL_NM", "SCHUL_KND_SC_CODE", "SCHUL_RDNMA", "ADRES_BRKDN",
          "HMPG_ADRES", "ATPT_OFCDC_ORG_CODE", "ATPT_OFCDC_ORG_NM", "LCTN_SC_CODE", "CLOSE_YN", "ABSCH_YN")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--snapshot", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9-]+", args.snapshot) or not 2024 <= args.year <= 2099:
        parser.error("invalid year or snapshot")
    raw = ROOT / "data/raw/schoolinfo/rosters" / args.snapshot
    output = ROOT / "data/derived/schoolinfo_4ga/rosters" / args.snapshot
    raw.mkdir(parents=True, exist_ok=False)
    output.mkdir(parents=True, exist_ok=False)
    browser = opener()
    with browser.open(SOURCE, timeout=15) as response:
        html = response.read().decode(response.headers.get_content_charset() or "euc-kr")
    module = re.search(r'<script src="(/js/new/dev/opendata\.js[^"\s]*)"', html)
    if not module:
        raise SystemExit("could not verify the public basic-data UI")
    with browser.open(BASE_URL + module[1], timeout=15) as response:
        code = response.read().decode("utf-8-sig")
    offices = re.findall(r"value\s*:\s*'(\d{2})',\s*label\s*:\s*'[^']+교육청',\s*use\s*:\s*'Y'", code)
    form = post(browser, BASE_URL + "/ng/go/pnnggo_a01_l3.do", {"GO_NO": "0"}, 20).body
    request = re.search(r'\$\.post\("(/openData\.do)"', form)
    browser_parameter = re.search(r'APIKEY\s*:\s*"([^"\s]+)"', form)
    if not request or not browser_parameter or len(set(offices)) < 15:
        raise SystemExit("could not verify the public UI's parameters")
    rows = []
    sources = []
    for office in dict.fromkeys(offices):
        time.sleep(0.4)
        result = post(browser, BASE_URL + request[1], {
            "APIKEY": browser_parameter[1], "APITYPE": "0", "DEPTHNO": "0",
            "SCHULKNDCODE": "04", "PBANYR": str(args.year), "LCTNSCCODE": office,
        }, 30)
        content = result.body.encode("utf-8")
        target = raw / f"public-basic-office-{office}.json"
        atomic_bytes(target, content)
        data = json.loads(result.body).get("list", [])
        if not data or any(row.get("SCHUL_KND_SC_CODE") != "04" or not row.get("SHL_IDF_CD") for row in data):
            raise SystemExit(f"unexpected basic-data response for office {office}")
        rows.extend({field: row.get(field) or "" for field in FIELDS} for row in data)
        sources.append({"office_selector": office, "rows": len(data),
                        "saved_path": target.relative_to(ROOT).as_posix(),
                        "sha256": hashlib.sha256(content).hexdigest()})
        print(f"office={office} schools={len(data)}", flush=True)
    keys = Counter(row["SHL_IDF_CD"] for row in rows)
    if any(count != 1 for count in keys.values()):
        raise SystemExit("duplicate basic-data school IDs")
    csv_text = io.StringIO(newline="")
    writer = csv.DictWriter(csv_text, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    atomic_bytes(output / "schoolinfo_public_basic_roster.csv", csv_text.getvalue().encode("utf-8-sig"))
    atomic_json(output / "public_basic_roster_summary.json", {
        "collected_at": now(), "source_url": SOURCE, "requested_year": args.year,
        "unique_school_ids": len(keys), "closed_flags": dict(Counter(row["CLOSE_YN"] for row in rows)),
        "education_office_selectors": len(sources), "sources": sources,
    })


if __name__ == "__main__":
    main()
