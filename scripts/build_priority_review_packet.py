"""Build a compact review packet for the priority calculus-related subjects."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path


PRIORITIES = {("2015", "수학Ⅱ"), ("2022", "대수"), ("2022", "미적분Ⅰ")}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--excerpt-limit", type=int, default=6000)
    args = parser.parse_args()

    rows: list[dict[str, object]] = []
    with args.input.open("r", encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            identity = (str(record.get("curriculum_hint") or ""), str(record.get("subject") or ""))
            if identity not in PRIORITIES:
                continue
            source = record.get("source") or {}
            rows.append({
                "review_id": "",
                "curriculum_hint": identity[0],
                "subject": identity[1],
                "school_name": source.get("school_name", ""),
                "region": source.get("region", ""),
                "candidate_name": source.get("candidate_name", ""),
                "saved_path": source.get("saved_path", ""),
                "sha256": record.get("sha256", ""),
                "review_score": record.get("review_score", 0),
                "subject_evidence_strength": record.get("subject_evidence_strength", 0),
                "subject_evidence_reasons": record.get("subject_evidence_reasons") or [],
                "marker_counts": record.get("marker_counts") or {},
                "action_tags": record.get("action_tags") or [],
                "evidence_text": str(record.get("evidence_text") or "")[: args.excerpt_limit],
            })
    rows.sort(key=lambda row: (row["curriculum_hint"], row["subject"], -int(row["review_score"]), str(row["school_name"])))
    counters: dict[tuple[str, str], int] = {}
    for row in rows:
        identity = (str(row["curriculum_hint"]), str(row["subject"]))
        counters[identity] = counters.get(identity, 0) + 1
        row["review_id"] = f"{identity[0]}-{identity[1]}-{counters[identity]:02d}"

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=args.output.stem + "_", suffix=".partial", dir=args.output.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    with temp_path.open("w", encoding="utf-8", newline="\n") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    os.replace(temp_path, args.output)
    print(json.dumps({"rows": len(rows), "counts": {f"{key[0]}:{key[1]}": value for key, value in counters.items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
