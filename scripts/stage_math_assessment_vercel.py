from __future__ import annotations

import json
import hashlib
import gzip
import io
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = Path(
    os.environ.get("MATH_ASSESSMENT_VERCEL_STAGE", ROOT / ".tmp" / "vercel-stage")
).resolve()
PACKAGED_DATA = Path(
    os.environ.get(
        "MATH_ASSESSMENT_PACKAGED_DATA",
        ROOT / "services" / "math-assessment-api" / "data",
    )
).resolve()

ROOT_FILES = (
    ".vercelignore",
    "package.json",
    "pnpm-lock.yaml",
    "pnpm-workspace.yaml",
    "vercel.json",
)
ROOT_SCRIPT_FILES = ("strip_next_protection_artifacts.mjs",)
WEB_FILES = (
    "LICENSE",
    "eslint.config.mjs",
    "next-env.d.ts",
    "next.config.ts",
    "package.json",
    "tsconfig.json",
)
API_FILES = ("requirements.txt",)


def copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def main() -> None:
    if not TARGET.is_relative_to(ROOT) or TARGET == ROOT:
        raise RuntimeError(f"unsafe Vercel stage target: {TARGET}")
    if TARGET.is_dir():
        shutil.rmtree(TARGET)
    TARGET.mkdir(parents=True)
    if not PACKAGED_DATA.is_dir() or not PACKAGED_DATA.is_relative_to(ROOT):
        raise RuntimeError(f"unsafe or missing packaged data source: {PACKAGED_DATA}")

    preview_path = ROOT / 'services/math-assessment-api/app/math_table_previews.json'
    registry = json.loads(preview_path.read_text('utf-8'))['items'] if preview_path.exists() else {}
    preview_assets = {}
    if registry:
        detail = PACKAGED_DATA / 'math_assessment_catalog_detail.sqlite'
        temporary = None
        if not detail.is_file():
            parts = sorted(PACKAGED_DATA.glob('math_assessment_catalog_detail.sqlite.gz.part-*'))
            if not parts:
                raise RuntimeError('Packaged detail archive is required for original-table validation')
            temporary = tempfile.TemporaryDirectory(prefix='table-stage-validation-', dir=ROOT / '.tmp')
            detail = Path(temporary.name) / 'detail.sqlite'
            compressed = io.BytesIO(b''.join(part.read_bytes() for part in parts))
            with gzip.GzipFile(fileobj=compressed) as archive, detail.open('wb') as output:
                shutil.copyfileobj(archive, output)
            manifest = json.loads((PACKAGED_DATA / 'release-manifest.json').read_text('utf-8'))
            expected = next(record['sha256'] for record in manifest['files'] if record['name'] == 'math_assessment_catalog_detail.sqlite')
            if hashlib.sha256(detail.read_bytes()).hexdigest() != expected:
                raise RuntimeError('Packaged detail checksum mismatch')
        with sqlite3.connect(detail.resolve().as_uri() + '?mode=ro&immutable=1', uri=True) as db:
            for item_id, entry in registry.items():
                row = db.execute('''SELECT i.source_html_zlib,c.source_sha256,i.extraction_status,i.title_basis,i.rubric_html_zlib
                    FROM assessment_items i JOIN cases c USING(case_id) WHERE i.item_id=?''', (item_id,)).fetchone()
                if not row or row[2] != 'bounded' or row[3] not in ('table', 'heading') or row[1] != entry['source_sha256'] or hashlib.sha256(row[0]).hexdigest() != entry['source_blob_sha256']:
                    raise RuntimeError('Original-table registry does not match the packaged public item: ' + item_id)
                if entry.get('rubric_excerpt_covered') and (
                    row[4] is None or hashlib.sha256(row[4]).hexdigest() != entry.get('rubric_blob_sha256')
                ):
                    raise RuntimeError('Complete rubric image does not match the packaged rubric: ' + item_id)
                for image in entry['source'] + entry.get('rubric', []):
                    asset = image['asset']
                    if len(asset) != 69 or not asset.endswith('.webp') or any(char not in '0123456789abcdef' for char in asset[:64]):
                        raise RuntimeError('Invalid original-table asset path')
                    preview_assets[asset] = image['asset_sha256']
        if temporary:
            temporary.cleanup()
        for asset, sha256 in preview_assets.items():
            path = ROOT / 'apps/math-assessment-web/public/source-tables' / asset
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != sha256:
                raise RuntimeError('Original-table asset is missing or changed: ' + asset)

    for name in ROOT_FILES:
        copy_file(ROOT / name, TARGET / name)
    for name in ROOT_SCRIPT_FILES:
        copy_file(ROOT / "scripts" / name, TARGET / "scripts" / name)

    web_source = ROOT / "apps" / "math-assessment-web"
    web_target = TARGET / "apps" / "math-assessment-web"
    shutil.copytree(web_source / "app", web_target / "app")
    if (web_source / "public").is_dir():
        shutil.copytree(web_source / "public", web_target / "public", ignore=shutil.ignore_patterns('source-tables'))
    for asset in preview_assets:
        copy_file(web_source / 'public/source-tables' / asset, web_target / 'public/source-tables' / asset)
    for name in WEB_FILES:
        copy_file(web_source / name, web_target / name)

    api_source = ROOT / "services" / "math-assessment-api"
    api_target = TARGET / "services" / "math-assessment-api"
    shutil.copytree(
        api_source / "app", api_target / "app",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    # The binding registry can cross the per-file upload guard as it grows.
    # Remove JSON whitespace only; every source/rubric hash and note is retained.
    staged_registry = api_target / "app/math_table_previews.json"
    if staged_registry.is_file():
        original_registry = json.loads(staged_registry.read_text("utf-8"))
        staged_registry.write_text(
            json.dumps(original_registry, ensure_ascii=False, separators=(",", ":")), "utf-8"
        )
        if json.loads(staged_registry.read_text("utf-8")) != original_registry:
            raise RuntimeError("Preview registry changed during whitespace compaction")
    for name in API_FILES:
        copy_file(api_source / name, api_target / name)
    for source in sorted(PACKAGED_DATA.iterdir()):
        if not source.is_file() or source.suffix in {".sqlite", ".partial"}:
            continue
        copy_file(source, api_target / "data" / source.name)

    files = sorted(path for path in TARGET.rglob("*") if path.is_file())
    oversized = [path for path in files if path.stat().st_size > 4_100_000]
    forbidden = [
        path
        for path in files
        if path.suffix.lower() in {".hwp", ".hwpx", ".pdf", ".sqlite", ".jsonl"}
    ]
    if oversized or forbidden:
        raise RuntimeError(
            "unsafe Vercel stage: "
            f"oversized={[path.name for path in oversized]}, "
            f"forbidden={[path.name for path in forbidden]}"
        )

    summary = {
        "target": str(TARGET),
        "file_count": len(files),
        "total_bytes": sum(path.stat().st_size for path in files),
        "largest_file_bytes": max(path.stat().st_size for path in files),
        "original_table_items": len(registry),
        "verified_original_table_assets": len(preview_assets),
    }
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
