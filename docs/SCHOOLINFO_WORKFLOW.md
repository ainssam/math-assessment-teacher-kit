# 학교알리미 4-가 수집·추출 따라 하기

학교알리미 4-가의 4월 공시는 1차, 9월 공시는 3차입니다. 수집기는 페이지에서 확인한 연도·차수와 다운로드 양식이 모두 요청한 값과 같을 때 첨부를 저장합니다. 학기는 파일명과 문서 표제에서 별도로 확인합니다. [학교알리미 2026 공시 지침](https://www.schoolinfo.go.kr/si/pi/pnsipi_a01_l0.do?searchYear=2026) · [2026년 9월 공시 안내](https://www.schoolinfo.go.kr/ng/ne/pnngne_a01_s0.do?ne_no=00000000000000000000000000000228)

## 1. 학교 목록 준비

처음에는 학교 한두 곳으로 시작하세요. `examples/school-roster.template.csv`의 헤더를 복사해 `data/roster.csv`를 만듭니다. 예제 행을 실제 값으로 바꿔 사용하세요.

| 열 | 넣을 값 |
| --- | --- |
| `school_id` | 파일명에 쓸 고유 식별자. 영문·숫자·밑줄·하이픈을 권장합니다. |
| `school_name` | 학교알리미에 표시되는 학교 이름 |
| `region_sido`, `region_sgg` | 시도명과 시군구명 |
| `school_code`, `neis_school_code` | 학교 기본정보의 표준학교코드. 두 열에 같은 값을 넣습니다. |
| `education_office_code` | 시도교육청 코드 |

나이스 학교기본정보에서 학교명·시도·교육청 코드와 표준학교코드를 확인할 수 있습니다. 이름이 같은 학교는 수집기에서 지역이나 교육청으로 구분합니다. [나이스 교육정보 개방 포털](https://open.neis.go.kr/)

## 2. 원문 수집

아래 명령은 목록의 최대 2개교를 조회합니다. 같은 명령을 다시 실행하면 다음 미조회 학교부터 이어집니다. 목록 전체를 조회하려면 `--limit 2`를 빼세요. 학교 목록은 첫 실행 때 함께 보존되므로 같은 작업 도중에 바꾸지 마세요. 실패 건만 다시 확인하려면 완료 후 `--retry-failed`를 추가합니다.

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/collect_schoolinfo_4ga_round.py --roster data/roster.csv --year 2026 --round 3 --limit 2
```

원문은 `data/raw/schoolinfo/4ga_rounds/2026-round-3/`에, 학교별 응답과 파일 목록은 `data/derived/schoolinfo_4ga/2026-round-3/`에 저장합니다. `collection_summary.json`의 학교 수와 파일 수를 먼저 읽으세요. 서버가 접근을 제한하거나 서비스 중단을 반환하면 수집을 멈춥니다.

## 3. 학기별 분석 후보 만들기

웹앱 설치 단계에서 설치한 kordoc과 아래의 Python 라이브러리를 사용합니다. 명부 전체를 조회한 뒤 실행하면 학기별 카탈로그, 확인표, 검증 결과, 로컬 SQLite 후보가 만들어집니다. 예를 들어 명부를 2개교로 작성했다면 두 학교를 모두 조회한 시점에 다음 단계로 넘어갈 수 있습니다.

```powershell
.\.venv\Scripts\python.exe -m pip install PyMuPDF==1.28.0
.\.venv\Scripts\python.exe -X utf8 scripts/build_schoolinfo_4ga_semester.py --year 2026 --semester 2
```

같은 원문을 다시 처리할 때는 `--revision v2`처럼 새 이름을 지정합니다. 기존 산출물과 비교하려면 다음 파일부터 확인하세요.

- `reconciliation.json`은 조회·수집·추출·학기 판정 수치를 보여 줍니다.
- `source_decisions.jsonl`은 문서별 출처, SHA-256, 학기·추출 판정을 기록합니다.
- `validation.json`은 JSONL 무결성과 출처 연결, 중복, 학교·과목 확인표의 행 수를 점검합니다.
- `detail_candidate.sqlite`는 제목과 상세 표를 검토할 로컬 후보입니다. README의 두 환경변수에 이 파일의 절대 경로를 지정해 로컬에서 볼 수 있습니다.

문서 한 개에 여러 과목이나 평가가 있을 수 있습니다. 문서 수, 학교·과목 사례 수, 수행평가 항목 수를 따로 셉니다. 과목이 미검출된 학교는 개설 여부가 확인되지 않은 상태로 해석합니다.

## 4. 화면에 내보내기 전 확인

평가명이 원문 표나 제목에서 확인되는지, 한 항목의 배점과 채점기준이 같은 과제에 속하는지, 과목·학기가 맞는지 대조합니다. 학기 표지가 없거나 서로 다르면 검토 대상으로 남깁니다. 수집 및 추출 무결성 검사와 공개 항목의 정확성 검사는 별개입니다.

상세 DB를 외부에 제공하기 전에는 제목·과목·공개 게이트와 렌더러 감사를 실시합니다. 원문은 학교알리미 링크로 안내하고, 공개할 발췌나 표는 별도로 검토합니다. [공개 기준](SOURCE_POLICY.md)
