"""Merge audited base and recovery detail databases into a staged database.

The output starts from a freshly rebuilt combined catalogue database.  Case
summaries and detail rows are then copied from the already audited base and
isolated recovery databases.  Inputs are read-only and the output is written
through a checked temporary SQLite file.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path


CASE_CHILD_TABLES = ("case_task_names", "case_action_tags")
DETAIL_TABLES = ("case_detail_status", "assessment_items", "assessment_item_rankings")


def columns(connection: sqlite3.Connection, schema: str, table: str) -> list[str]:
    return [
        str(row[1])
        for row in connection.execute(f"PRAGMA {schema}.table_info({table})")
    ]


def table_count(connection: sqlite3.Connection, schema: str, table: str) -> int:
    return int(connection.execute(f"SELECT COUNT(*) FROM {schema}.{table}").fetchone()[0])


def copy_rows(
    connection: sqlite3.Connection,
    target_table: str,
    source_schemas: tuple[str, ...],
) -> int:
    target_columns = columns(connection, "main", target_table)
    quoted = ",".join(f'"{column}"' for column in target_columns)
    inserted = 0
    for schema in source_schemas:
        if set(columns(connection, schema, target_table)) != set(target_columns):
            raise SystemExit(f"schema mismatch for {schema}.{target_table}")
        before = connection.total_changes
        connection.execute(
            f"INSERT INTO main.{target_table} ({quoted}) "
            f"SELECT {quoted} FROM {schema}.{target_table}"
        )
        inserted += connection.total_changes - before
    return inserted


def replace_case_rows(connection: sqlite3.Connection, source_schemas: tuple[str, ...]) -> int:
    target_columns = columns(connection, "main", "cases")
    quoted = ",".join(f'"{column}"' for column in target_columns)
    inserted = 0
    for schema in source_schemas:
        if set(columns(connection, schema, "cases")) != set(target_columns):
            raise SystemExit(f"schema mismatch for {schema}.cases")
        before = connection.total_changes
        connection.execute(
            f"INSERT OR REPLACE INTO main.cases ({quoted}) "
            f"SELECT {quoted} FROM {schema}.cases"
        )
        inserted += connection.total_changes - before
    return inserted


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--combined-base-db", type=Path, required=True)
    parser.add_argument("--base-detail-db", type=Path, required=True)
    parser.add_argument("--recovery-detail-db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest-output", type=Path, required=True)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    inputs = (args.combined_base_db, args.base_detail_db, args.recovery_detail_db)
    missing = [str(path) for path in inputs if not path.is_file()]
    if missing:
        raise SystemExit(f"missing inputs: {missing}")
    if (args.output.exists() or args.manifest_output.exists()) and not args.replace:
        raise SystemExit("output exists; use --replace for an atomic rebuild")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=args.output.stem + "_", suffix=".partial", dir=args.output.parent
    )
    os.close(descriptor)
    temporary = Path(temp_name)
    shutil.copy2(args.combined_base_db, temporary)
    started = dt.datetime.now(dt.UTC)
    try:
        with sqlite3.connect(temporary, uri=True) as connection:
            connection.execute("PRAGMA journal_mode = DELETE")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.execute("PRAGMA foreign_keys = OFF")
            # ATTACH resolves unqualified DDL against attached schemas when the
            # table is absent in ``main``.  Open both evidence databases as
            # immutable read-only URIs and never issue unqualified DROP DDL.
            base_uri = args.base_detail_db.resolve().as_uri() + "?mode=ro&immutable=1"
            recovery_uri = (
                args.recovery_detail_db.resolve().as_uri() + "?mode=ro&immutable=1"
            )
            connection.execute("ATTACH DATABASE ? AS base_detail", (base_uri,))
            connection.execute("ATTACH DATABASE ? AS recovery_detail", (recovery_uri,))

            base_ids = {
                str(row[0]) for row in connection.execute("SELECT case_id FROM base_detail.cases")
            }
            recovery_ids = {
                str(row[0]) for row in connection.execute("SELECT case_id FROM recovery_detail.cases")
            }
            combined_ids = {
                str(row[0]) for row in connection.execute("SELECT case_id FROM main.cases")
            }
            if base_ids & recovery_ids:
                raise SystemExit(f"base/recovery case collision: {len(base_ids & recovery_ids)}")
            if combined_ids != base_ids | recovery_ids:
                raise SystemExit(
                    "combined catalogue case mismatch: "
                    f"combined={len(combined_ids)} sources={len(base_ids | recovery_ids)}"
                )

            connection.execute("DELETE FROM case_task_names")
            connection.execute("DELETE FROM case_action_tags")
            replaced_cases = replace_case_rows(connection, ("base_detail", "recovery_detail"))
            child_counts = {
                table: copy_rows(connection, table, ("base_detail", "recovery_detail"))
                for table in CASE_CHILD_TABLES
            }

            existing_detail_tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM main.sqlite_master WHERE type='table' "
                    "AND name IN ('case_detail_status', 'assessment_items', "
                    "'assessment_item_rankings')"
                )
            }
            if existing_detail_tables:
                raise SystemExit(
                    "combined base DB unexpectedly contains detail tables: "
                    f"{sorted(existing_detail_tables)}"
                )
            for table in ("case_detail_status", "assessment_items", "assessment_item_rankings"):
                create_sql = connection.execute(
                    "SELECT sql FROM base_detail.sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ).fetchone()
                if not create_sql or not create_sql[0]:
                    raise SystemExit(f"missing source table definition: {table}")
                connection.execute(str(create_sql[0]))
            for (index_sql,) in connection.execute(
                """
                SELECT sql FROM base_detail.sqlite_master
                WHERE type = 'index'
                  AND tbl_name IN ('case_detail_status', 'assessment_items',
                                   'assessment_item_rankings')
                  AND sql IS NOT NULL
                ORDER BY name
                """
            ):
                connection.execute(str(index_sql))
            detail_counts = {
                table: copy_rows(connection, table, ("base_detail", "recovery_detail"))
                for table in DETAIL_TABLES
            }

            connection.execute("INSERT INTO cases_fts(cases_fts) VALUES('rebuild')")
            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value_json) VALUES('source_catalog_rows', ?)",
                (json.dumps(len(combined_ids)),),
            )
            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value_json) VALUES('recovery_catalog_rows', ?)",
                (json.dumps(len(recovery_ids)),),
            )
            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value_json) VALUES('detail_schema_version', '2')"
            )
            connection.commit()
            connection.execute("PRAGMA foreign_keys = ON")
            violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise SystemExit(f"foreign-key violations: {len(violations)}")
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise SystemExit(f"SQLite integrity check failed: {integrity}")
            counts = {
                "cases": table_count(connection, "main", "cases"),
                "case_detail_status": table_count(connection, "main", "case_detail_status"),
                "assessment_items": table_count(connection, "main", "assessment_items"),
                "assessment_item_rankings": table_count(connection, "main", "assessment_item_rankings"),
                "fts_rows": table_count(connection, "main", "cases_fts"),
                "base_cases": len(base_ids),
                "recovery_cases": len(recovery_ids),
                "case_rows_replaced": replaced_cases,
                **{f"copied_{key}": value for key, value in child_counts.items()},
                **{f"copied_{key}": value for key, value in detail_counts.items()},
            }
            if not (
                counts["cases"]
                == counts["case_detail_status"]
                == counts["fts_rows"]
                == len(combined_ids)
            ):
                raise SystemExit(f"merged counts do not reconcile: {counts}")
            if counts["assessment_items"] != counts["assessment_item_rankings"]:
                raise SystemExit(f"item/ranking counts do not reconcile: {counts}")
            connection.execute("VACUUM")
        try:
            os.replace(temporary, args.output)
        except PermissionError:
            # Windows indexing may retain the completed temporary database for
            # a few moments.  SQLite backup preserves transactional integrity
            # without requiring a filesystem rename.
            source_uri = temporary.resolve().as_uri() + "?mode=ro&immutable=1"
            with sqlite3.connect(source_uri, uri=True) as source, sqlite3.connect(
                args.output
            ) as destination:
                source.backup(destination)
                destination.commit()
            try:
                temporary.unlink()
            except PermissionError:
                print(f"detail_merge_checkpoint_retained={temporary}", flush=True)
    except BaseException:
        print(f"detail_merge_checkpoint={temporary}", flush=True)
        raise

    manifest = {
        "schema_version": 1,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "elapsed_seconds": round((dt.datetime.now(dt.UTC) - started).total_seconds(), 3),
        "inputs": {
            "combined_base_db": str(args.combined_base_db.resolve()),
            "base_detail_db": str(args.base_detail_db.resolve()),
            "recovery_detail_db": str(args.recovery_detail_db.resolve()),
        },
        "output": {
            "path": str(args.output.resolve()),
            "bytes": args.output.stat().st_size,
            "sha256": sha256(args.output),
        },
        "counts": counts,
        "quality_gates": {
            "case_ids_disjoint": True,
            "all_cases_have_detail": True,
            "items_have_rankings": True,
            "foreign_keys_clean": True,
            "sqlite_integrity": True,
        },
    }
    args.manifest_output.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
