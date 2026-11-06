"""Add source-backed si/gun/gu values to the published assessment catalog.

Districts are taken only from the SCHOOLINFO school roster by exact school_code.
The script never infers a district from a school name or address.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def school_districts(path: Path) -> dict[str, tuple[str, str]]:
    output: dict[str, tuple[str, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            code = str(row.get("school_code") or "").strip()
            region = str(row.get("region") or row.get("region_sido") or "").strip()
            district = str(row.get("district") or row.get("region_sgg") or "").strip()
            if not code or not region or not district:
                continue
            value = (region, district)
            previous = output.get(code)
            if previous and previous != value:
                raise SystemExit(
                    f"conflicting school roster values for {code}: {previous} != {value}"
                )
            output[code] = value
    if not output:
        raise SystemExit("school roster has no usable school_code/region/district records")
    return output


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database",
        type=Path,
        default=root / "data/publish/math_assessment_catalog_detail.sqlite",
    )
    parser.add_argument(
        "--schools", type=Path, default=root / "data/derived/schoolinfo_schools.csv"
    )
    parser.add_argument(
        "--manifest-output",
        type=Path,
        default=root / "data/publish/math_assessment_district_enrichment.json",
    )
    args = parser.parse_args()

    if not args.database.is_file() or not args.schools.is_file():
        raise SystemExit("database and schools CSV must exist")
    roster = school_districts(args.schools)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=args.database.stem + "_district_", suffix=".partial", dir=args.database.parent
    )
    os.close(descriptor)
    temporary = Path(temp_name)
    try:
        shutil.copy2(args.database, temporary)
        connection = sqlite3.connect(temporary)
        try:
            columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(cases)")}
            if "district" not in columns:
                connection.execute("ALTER TABLE cases ADD COLUMN district TEXT NOT NULL DEFAULT ''")
            rows = connection.execute("SELECT case_id, school_code, region FROM cases").fetchall()
            updates: list[tuple[str, str]] = []
            missing_codes: list[str] = []
            mismatched_regions: list[str] = []
            for case_id, school_code, region in rows:
                value = roster.get(str(school_code))
                if value is None:
                    missing_codes.append(str(case_id))
                    continue
                roster_region, district = value
                if roster_region != str(region):
                    mismatched_regions.append(str(case_id))
                    continue
                updates.append((district, str(case_id)))
            if missing_codes or mismatched_regions:
                raise SystemExit(
                    "source-backed district coverage failed: "
                    f"missing_school_code={len(missing_codes)}, "
                    f"region_mismatch={len(mismatched_regions)}"
                )
            connection.executemany("UPDATE cases SET district = ? WHERE case_id = ?", updates)
            remaining = int(
                connection.execute(
                    "SELECT COUNT(*) FROM cases WHERE district = ''"
                ).fetchone()[0]
            )
            if remaining:
                raise SystemExit(f"district enrichment left {remaining} empty case values")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_cases_region_district_subject "
                "ON cases(region, district, subject, review_score DESC)"
            )
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            if integrity != "ok":
                raise SystemExit(f"SQLite integrity check failed: {integrity}")
            counts = {
                "cases": len(rows),
                "updated": len(updates),
                "regions": int(
                    connection.execute(
                        "SELECT COUNT(DISTINCT region) FROM cases"
                    ).fetchone()[0]
                ),
                "districts": int(
                    connection.execute(
                        "SELECT COUNT(DISTINCT district) FROM cases"
                    ).fetchone()[0]
                ),
            }
            connection.commit()
        finally:
            connection.close()
        try:
            os.replace(temporary, args.database)
        except PermissionError:
            # Windows Search or a recently closed API test can retain a
            # read-handle briefly. SQLite's backup API still replaces every
            # page transactionally without deleting the destination first.
            with sqlite3.connect(temporary) as source, sqlite3.connect(
                args.database
            ) as destination:
                source.backup(destination)
                destination.commit()
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except PermissionError:
                # A failed replacement must leave the complete temporary DB intact
                # instead of risking a partial deletion on Windows.
                pass

    manifest = {
        "database": str(args.database.resolve().relative_to(root)),
        "database_sha256": sha256(args.database),
        "schools": str(args.schools.resolve().relative_to(root)),
        "schools_sha256": sha256(args.schools),
        "match_method": "exact school_code and region from SCHOOLINFO school roster",
        "counts": counts,
    }
    args.manifest_output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
