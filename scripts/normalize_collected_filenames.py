"""Rename collected attachments to stable, readable source-backed names."""
from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any


INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(value: str, limit: int = 90) -> str:
    value = unicodedata.normalize("NFC", value).strip()
    value = INVALID.sub(" ", value)
    value = re.sub(r"\s+", "_", value)
    value = re.sub(r"_+", "_", value).strip(" ._")
    return (value or "공식자료")[:limit].rstrip(" ._")


def id_sort(value: str) -> tuple[int, str]:
    match = re.search(r"\d+", value or "")
    return (int(match.group()) if match else 999999, value or "")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    args = parser.parse_args()

    run = args.run.resolve()
    files_root = (run / "files").resolve()
    if run not in files_root.parents or not files_root.is_dir():
        raise RuntimeError(f"unsafe or missing files root: {files_root}")

    catalog_rows: list[dict[str, Any]] = json.loads(args.catalog.read_text(encoding="utf-8"))
    catalog = {str(row["id"]): row for row in catalog_rows}
    manifest_path = run / "download_manifest.csv"
    with manifest_path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        saved = row.get("saved_path", "")
        if saved and row.get("status") in {"downloaded", "duplicate"}:
            grouped[saved].append(row)

    plans: list[dict[str, Any]] = []
    counters: dict[tuple[str, str], int] = defaultdict(int)
    totals: CounterLike = CounterLike()
    unique_existing = []
    for saved, occurrences in grouped.items():
        old = (run / saved).resolve()
        if old.exists() and files_root in old.parents:
            seed_ids = sorted({row.get("seed_id", "") for row in occurrences if row.get("seed_id")}, key=id_sort)
            primary = seed_ids[0] if seed_ids else "SRC"
            title = str(catalog.get(primary, {}).get("title") or occurrences[0].get("title") or "공식자료")
            unique_existing.append((saved, old, occurrences, seed_ids, primary, title))
            totals[(primary, old.suffix.lower())] += 1

    for saved, old, occurrences, seed_ids, primary, title in sorted(unique_existing, key=lambda x: (id_sort(x[4]), x[0])):
        key = (primary, old.suffix.lower())
        counters[key] += 1
        suffix = f"_{counters[key]:02d}" if totals[key] > 1 else ""
        new_name = f"{primary}_{safe_name(title)}{suffix}{old.suffix.lower()}"
        new = old.parent / new_name
        collision = 2
        while new.exists() and new.resolve() != old:
            new = old.parent / f"{primary}_{safe_name(title)}{suffix}_{collision}{old.suffix.lower()}"
            collision += 1
        plans.append({
            "old_saved_path": saved,
            "old": old,
            "new": new,
            "new_saved_path": str(new.relative_to(run)),
            "sha256": occurrences[0].get("sha256", ""),
            "seed_ids": seed_ids,
            "title": title,
        })

    replacement = {plan["old_saved_path"]: plan["new_saved_path"] for plan in plans}
    for plan in plans:
        if plan["old"] != plan["new"]:
            plan["old"].rename(plan["new"])
    for row in rows:
        if row.get("saved_path") in replacement:
            row["saved_path"] = replacement[row["saved_path"]]

    with manifest_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    derived_root = run / "derived"
    if derived_root.is_dir():
        for jsonl_path in derived_root.glob("*.jsonl"):
            derived_rows = [
                json.loads(line)
                for line in jsonl_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            changed = False
            for item in derived_rows:
                if item.get("saved_path") in replacement:
                    item["saved_path"] = replacement[item["saved_path"]]
                    changed = True
            if changed:
                jsonl_path.write_text(
                    "\n".join(json.dumps(item, ensure_ascii=False) for item in derived_rows) + "\n",
                    encoding="utf-8",
                )
    map_path = run / "filename_map.csv"
    with map_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=("old_saved_path", "new_saved_path", "sha256", "seed_ids", "title"),
        )
        writer.writeheader()
        for plan in plans:
            writer.writerow({
                "old_saved_path": plan["old_saved_path"],
                "new_saved_path": plan["new_saved_path"],
                "sha256": plan["sha256"],
                "seed_ids": ";".join(plan["seed_ids"]),
                "title": plan["title"],
            })
    print(json.dumps({"renamed": len(plans), "map": str(map_path)}, ensure_ascii=False))


class CounterLike(defaultdict[tuple[str, str], int]):
    def __init__(self) -> None:
        super().__init__(int)


if __name__ == "__main__":
    main()
