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

여러 지역의 학교를 조사할 때는 학교알리미 목록도 함께 받아 대조하세요. 공개 목록은 과거 공시를 열 수 있는 학교를 포함하므로 현재 운영 학교 수는 별도 자료에서 확인합니다. 방송통신고와 일부 고교 과정 각종학교는 ‘기타학교’에 들어 있으므로 아래 두 번째 명령으로 따로 확인할 수 있습니다. [학교알리미 학교별 공시](https://www.schoolinfo.go.kr/ei/ss/pneiss_a03_s0.do) · [전국초중등학교위치표준데이터](https://www.data.go.kr/data/15021148/standard.do)

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/fetch_schoolinfo_high_school_directory.py --snapshot 2026-11-06
.\.venv\Scripts\python.exe -X utf8 scripts/fetch_schoolinfo_high_school_directory.py --snapshot 2026-11-06 --school-kind other
.\.venv\Scripts\python.exe -X utf8 scripts/fetch_schoolinfo_public_basic_roster.py --year 2026 --snapshot 2026-11-06-public-basic
```

명부를 대조할 때 학교명과 시도를 함께 비교합니다. 일치하는 행이 여럿이면 주소와 학교알리미 ID를 확인합니다. 같은 이름으로 검색되더라도 지역이 다른 학교의 문서는 별도로 두세요. 세 번째 명령은 일반 학교 검색에 나오지 않는 학교를 확인할 수 있도록 기준연도의 학교기본정보를 받아 옵니다. [학교알리미 공개용 데이터](https://www.schoolinfo.go.kr/ng/go/pnnggo_a01_l2.do)

## 2. 원문 수집

아래 명령은 목록의 최대 2개교를 조회합니다. 같은 명령을 다시 실행하면 다음 미조회 학교부터 이어집니다. 목록 전체를 조회하려면 `--limit 2`를 빼세요. 학교 목록은 첫 실행 때 함께 보존되므로 같은 작업 도중에 바꾸지 마세요. 실패 건만 다시 확인하려면 완료 후 `--retry-failed`를 추가합니다.

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/collect_schoolinfo_4ga_round.py --roster data/roster.csv --year 2026 --round 3 --limit 2
```

원문은 `data/raw/schoolinfo/4ga_rounds/2026-round-3/`에, 학교별 응답과 파일 목록은 `data/derived/schoolinfo_4ga/2026-round-3/`에 저장합니다. `collection_summary.json`의 학교 수와 파일 수를 먼저 읽으세요. 서버가 접근을 제한하거나 서비스 중단을 반환하면 수집을 멈춥니다.

확인한 학교알리미 ID로 직접 조회하려면 명부에 `schoolinfo_uuid`와 `schoolinfo_code` 두 열을 추가합니다. 학교 목록 CSV에서 각각 `SHL_IDF_CD`, `SHL_CD`를 가져오고, 수집 명령에 `--official-directory`와 그 CSV 경로를 지정하세요. 기존 명부를 유지하며 일부 학교의 ID만 쓰려면 대조표를 `--identity-crosswalk`로 추가합니다. 대조표에는 명부와 같은 `school_id`, `school_code`, `school_name`, `region_sido`가 필요합니다.

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

목록에 해당 공시 차수가 없는 경우, 4-가 화면에 자료 없음이 표시되는 경우, 다운로드 또는 본문 추출이 실패한 경우를 각각 기록하세요. 대상 차수의 원문이 있는지를 먼저 확인해야 학교별 미확인 사유를 다시 조사할 수 있습니다.

## 4. 화면에 내보내기 전 확인

평가명이 원문 표나 제목에서 확인되는지, 한 항목의 배점과 채점기준이 같은 과제에 속하는지, 과목·학기가 맞는지 대조합니다. 학기 표지가 없거나 서로 다르면 검토 대상으로 남깁니다. 수집 및 추출 무결성 검사와 공개 항목의 정확성 검사는 별개입니다.

상세 DB를 외부에 제공하기 전에는 제목·과목·공개 게이트와 렌더러 감사를 실시합니다. 원문은 학교알리미 링크로 안내하고, 공개할 발췌나 표는 별도로 검토합니다. [공개 기준](SOURCE_POLICY.md)
