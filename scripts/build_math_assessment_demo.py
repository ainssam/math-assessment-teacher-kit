"""Create a small, synthetic catalog for running the app locally."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from scripts.build_math_assessment_detail_db import (
    SCHEMA_SQL as DETAIL_SCHEMA,
)
from scripts.build_math_assessment_detail_db import build_details, synchronize_case_summaries
from scripts.build_math_assessment_publish_db import (
    CASE_INSERT_SQL,
    SCHEMA_SQL,
    case_values,
    insert_subjects,
)


TEXT = """# 2026학년도 2학기 (대수)과 교수학습 및 평가 운영 계획
## 수행평가 세부 기준
1. 지수 함수로 빛의 세기 변화 분석하기
<table>
<tr><th>수행평가명</th><td>지수 함수로 빛의 세기 변화 분석하기</td></tr>
<tr><th>평가 개요</th><td>가상의 측정값을 지수 함수로 표현하고 적합성을 설명한다.</td></tr>
<tr><th>평가 방법</th><td>프로젝트</td></tr>
<tr><th>반영 비율</th><td>20%</td></tr>
</table>
<table>
<tr><th>평가요소</th><th>채점기준</th><th>점수</th></tr>
<tr><td>모델 구성</td><td>변화율이 일정한 비율이라는 가정을 설명함</td><td>10점</td></tr>
<tr><td>모델 검토</td><td>가상 자료와 식의 차이가 생기는 구간을 설명함</td><td>10점</td></tr>
</table>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/demo/demo.sqlite"))
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"output already exists: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(TEXT.encode()).hexdigest()
    source = {
        "school_code": "DEMO1", "school_name": "가상 예제 고등학교",
        "region": "서울특별시", "candidate_name": "가상 예제 2026학년도 2학기 대수 평가계획.md",
    }
    case = {
        "sha256": digest, "subject": "대수", "resolved_curriculum": "2022",
        "curriculum_resolution_basis": "synthetic_demo",
        "source": source, "academic_years": [2026], "grades": [2], "semesters": [2],
        "extract_status": "ok", "char_count": len(TEXT), "evidence_text": TEXT,
        "action_tags": ["프로젝트"], "marker_counts": {"rubric": 1, "assessment_method": 1},
    }
    with tempfile.TemporaryDirectory(dir=args.output.parent) as temp_dir:
        work = Path(temp_dir)
        catalog = work / "catalog.jsonl"
        source_text = work / "source.jsonl"
        catalog.write_text(json.dumps(case, ensure_ascii=False) + "\n", encoding="utf-8")
        source_text.write_text(
            json.dumps({"sha256": digest, "text": TEXT}, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        temp_db = work / "demo.sqlite"
        with closing(sqlite3.connect(temp_db)) as connection:
            connection.executescript(SCHEMA_SQL + DETAIL_SCHEMA)
            connection.execute(CASE_INSERT_SQL, case_values(case, {"DEMO1": ("서울특별시", "가상구")}))
            insert_subjects(
                connection,
                {"subject_groups": {"2022:대수": {
                    "curriculum": "2022", "subject": "대수", "documents": 1,
                    "schools": 1, "academic_years": [2026], "grade2_documents": 1,
                    "rubric_documents": 1, "assessment_method_documents": 1,
                    "action_tag_document_counts": {"프로젝트": 1},
                    "action_tag_school_counts": {"프로젝트": 1},
                }}},
                {"by_subject": {"2022:대수": {"found": 1}}},
            )
            connection.execute("INSERT INTO metadata VALUES (?, ?)", ("dataset_scope", '"synthetic_demo"'))
            build_details(connection, catalog, source_text)
            synchronize_case_summaries(connection)
            connection.execute("PRAGMA user_version = 2")
            connection.commit()
            if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise SystemExit("demo database integrity check failed")
        os.replace(temp_db, args.output)
    print(f"Created synthetic catalog: {args.output}")


if __name__ == "__main__":
    main()
