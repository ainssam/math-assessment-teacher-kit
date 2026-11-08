"""Match source-authored codes within the requested curriculum and course."""

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

REGISTRIES = {
    year: json.loads(Path(__file__).with_name(f"math_standards_{year}.json").read_text("utf-8"))
    for year in ("2015", "2022")
}
STANDARDS = {
    year: {entry["key"]: entry for entry in registry["standards"]}
    for year, registry in REGISTRIES.items()
}
CODE = re.compile(r"(?<![\dA-Za-z])(?:10|12)[가-힣A-Za-z\d]+-?\d{2}-\d{2}(?!\d)")


@lru_cache(maxsize=4096)
def source_standard_codes(raw: str, subject: str, curriculum: str = "2022") -> frozenset[str]:
    values = json.loads(raw)
    normalized = unicodedata.normalize("NFKC", " ".join(values))
    normalized = re.sub(r"\s+", "", normalized).replace("−", "-").replace("–", "-")
    standards = STANDARDS.get(curriculum, {})
    return frozenset(
        code for code in CODE.findall(normalized)
        if code in standards and standards[code]["subject"] == subject
    )
