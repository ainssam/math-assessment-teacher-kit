# 수학 수행평가 서비스 데이터 사전

## 목적과 공개 경계

`data/publish/math_assessment_catalog.sqlite`는 교사용 웹 화면과 API가 사용하는
읽기 전용 축약 데이터다. 학교알리미 원문, 전체 추출문, 로컬 원문 경로는 이
데이터베이스에 넣지 않는다.

각 사례에는 최대 902자의 정규화 발췌, 원문 해시, 학교명, 과목 판별 근거,
공개 학교알리미 페이지 URL만 남긴다. 발췌는 사례 탐색을 위한 근거이며 원문을
대체하지 않는다.

## 테이블

### `metadata`

빌드 스키마 버전, 원본 검증 통과 여부, 자료 해석 경고와 공개 정책을 보존한다.

### `subject_stats`

교육과정 × 과목별 문서·학교·학년·평가근거 집계다. 2015 개정 9개 조합과
2022 개정 15개 조합 외에 교육과정을 확정하지 못한 공유 과목 그룹도 별도로
보존한다.

`coverage_*` 값은 학교 2,407곳 확인표에서 가져온다. `coverage_not_found`는
수집한 평가계획에서 과목이 발견되지 않았다는 뜻이며 미개설을 의미하지 않는다.

### `subject_action_tags`

과목별 탐구, 프로젝트, 문제해결, 발표, 보고서 등 규칙 기반 활동 표지의 문서 수와
학교 수다. 의미 기반으로 검토 완료된 과제 유형이 아니라 자동 탐지 신호다.

### `cases`

한 원문 × 한 수학 과목의 정규화 사례다.

| 필드 | 의미 |
|---|---|
| `case_id` | 원문 해시·교육과정·과목으로 만든 안정 식별자 |
| `source_sha256` | 원문 파일의 SHA-256 |
| `curriculum`, `subject` | 판별된 교육과정과 과목 |
| `curriculum_basis` | 교육과정 판별 근거 |
| `school_code`, `school_name`, `region` | 공개 학교 메타데이터 |
| `academic_years_json`, `grades_json`, `semesters_json` | 원문에서 확인한 연도·학년·학기 |
| `candidate_name` | 공개 첨부파일 이름 |
| `source_url` | 학교알리미 공시 페이지 |
| `primary_task_name` | 규칙 기반 대표 수행평가명 후보 |
| `task_names_json`, `action_tags_json` | 과제명 후보와 활동 표지 |
| `*_marker_count` | 루브릭·성취기준·배점·평가방법 표지 수 |
| `review_score` | 증거 완결성 점수이며 설계 품질 점수가 아님 |
| `evidence_excerpt` | 전체 원문 대신 제공하는 짧은 근거 발췌 |
| `source_char_count` | 원본 추출문의 길이, 본문 자체는 미수록 |

### `case_action_tags`, `case_task_names`

활동 표지와 과제명 후보를 검색하기 위한 정규화 관계 테이블이다.

### `cases_fts`

대표 과제명, 근거 발췌, 학교명, 과목의 한글 전문 검색용 FTS5 색인이다.

## 색인과 대표 조회

- `idx_cases_curriculum_subject_review`: 교육과정·과목별 사례 조회
- `idx_cases_subject_review`: 교육과정 미확정 공유 사례를 포함한 과목 조회
- `idx_cases_region_subject`: 지역·과목 조회
- `idx_case_action_tags_tag_case`: 활동 유형 필터

빌드 뒤 `PRAGMA optimize`를 실행하고 검증 스크립트가 대표 조회의
`EXPLAIN QUERY PLAN`에서 해당 색인 사용 여부를 확인한다.

## 재생성

```powershell
node scripts/run-python.mjs scripts/build_math_assessment_publish_db.py
node scripts/run-python.mjs scripts/validate_math_assessment_publish_db.py
```

기존 발행물을 원자적으로 재생성할 때만 첫 명령에 `--replace`를 붙인다.
원본 `data/raw/`와 `data/derived/`는 수정하지 않는다.
