# 내 AI 도구로 수행평가 사례를 읽고 비교하기

**ChatGPT·Claude에서 코딩 없이 쓰려면 [선생님용 연결·활용 안내](TEACHER_AI_GUIDE.md)를 먼저 보세요.** 아래는 Python 도구나 로컬 AI 작업 폴더를 사용하는 분을 위한 별도 안내입니다.

이 저장소에는 **공개 아카이브를 읽는 작은 Python 도구**가 들어 있습니다. 개인 Codex 같은 로컬 AI 도구가 이 명령을 실행하고, 실제 본문·채점표·원문 그림 링크를 근거로 비교하도록 쓸 수 있습니다. Python으로 직접 실행한 결과를 AI에 첨부해도 됩니다.

CLI는 무료 공개 조회 API에 GET 요청만 보냅니다. LLM 호출·API 키·로그인·운영 DB·추가 Python 패키지가 필요하지 않습니다. CLI와 별도로 개인 AI가 호출할 수 있는 **MCP 조회 도구 6개를 제공하며, 2026년 11월 9일 공개 운영 주소의 실제 SDK 연결 검증까지 마쳤습니다.** 연결 설정과 확인 범위는 [MCP 연결 안내](MCP_CONNECTION.md)를 보세요. 어느 경로도 서버에서 AI 분석을 대신 실행하지 않습니다.

## 1. 준비

1. 공개 저장소를 내려받거나 복제합니다. 실제 학교 원문과 운영 DB는 포함하지 않습니다.
2. Python 3.10 이상을 설치하고 터미널에서 `python --version`을 확인합니다. Windows에서 `python`이 인식되지 않으면 같은 명령의 `python`을 `py -3`으로 바꿔 보세요.
3. Codex에서는 저장소의 **`research` 폴더를 작업 폴더로 열고 새 대화**를 시작합니다. “이 폴더의 AGENTS.md를 읽고 수행평가 자료 연구를 도와줘”라고 요청합니다. 공식 문서는 현재 작업 디렉터리까지의 AGENTS.md가 지침에 포함되는 방식을 설명합니다. [OpenAI의 폴더 지침 안내](https://learn.chatgpt.com/docs/agent-configuration/agents-md)

Codex에서 ChatGPT 계정으로 로그인하는 구독 이용과 API 키로 로그인하는 사용량 과금은 별도 방식입니다. 구독을 사용하는 경우 해당 계정으로 직접 로그인하고 이용 가능 범위·한도를 확인하세요. 이 저장소에 인증정보를 입력하거나 공유할 필요가 없습니다. [OpenAI의 로그인 방식 안내](https://learn.chatgpt.com/docs/auth)

## 2. 첫 질문

Codex에 다음처럼 요청하면 됩니다. 아래는 실제 학교 데이터를 담지 않은 질문 예시입니다.

> 2026학년도 2학기, 2022 개정 기하 사례를 최대5개 찾아줘. research/AGENTS.md를 지키고 공개 CLI로 실제 자료를 조회해. 읽은 과제 수와 검색 일치 사례 수를 구분하고, 각 과제의 본문·채점표·공식 출처를 확인한 뒤 비교할 점을 정리해줘.

도구가 로컬 명령이나 인터넷 접근을 사용할 수 있어야 합니다. 사용할 수 없으면 교사가 아래 명령을 직접 실행하고 결과 JSON을 첨부하면 됩니다. CLI가 자료를 읽었다고 해서 AI가 원문 그림까지 봤다는 뜻은 아닙니다. 중요한 수식·배점·열 배치는 그림을 함께 확인하세요.

## 3. 직접 실행

다음 명령은 **저장소 최상위 폴더**에서 실행합니다. `research` 폴더 안에서는 `scripts/`를 `../scripts/`로 바꾸면 됩니다. 기본 주소는 `https://suhaeng-math.vercel.app/api/v1/`입니다.

```powershell
python scripts/math_assessment_research.py --help
python scripts/math_assessment_research.py meta
python scripts/math_assessment_research.py search --curriculum 2022 --subject "기하" --academic-year 2026 --semester 2 --limit 5
python scripts/math_assessment_research.py bundle --curriculum 2022 --subject "기하" --academic-year 2026 --semester 2 --limit 5 --output research/outputs/geometry-2026-s2.json
```

`search`는 **사례 목록**을 돌려줍니다. `bundle`은 그 사례 페이지에 있는 과제 중 최대5개의 상세 본문과 채점표를 읽습니다. 하나의 사례에 과제가 여러 개이므로 “사례5개”와 “과제5개”는 다릅니다.

한 과제를 더 읽거나 두 과제를 직접 묶으려면, 위 결과에 실제로 반환된 item_id를 사용합니다. 아래 `<첫 번째 ID>` 같은 부분은 그대로 실행하지 말고 실제 ID로 바꾸세요.

```powershell
python scripts/math_assessment_research.py item <과제 ID>
python scripts/math_assessment_research.py bundle --item-id <첫 번째 ID> --item-id <두 번째 ID> --limit 2 --output research/outputs/comparison.json
```

본문은 `source.text`, 채점표는 `rubric.text`로 분리됩니다. 학교·과목·교육과정·학년도·학기·개요·평가방법·배점·비율·성취기준·`source_notes`를 함께 제공합니다. `source.previews`와 `rubric.previews`는 원문 그림 URL, `official_source_url`은 학교알리미 공식 출처, `web_case_url`은 해당 과제가 선택된 웹 사례 주소입니다. 그림 파일을 자동으로 내려받지는 않습니다. HTML도 필요할 때만 `--include-html`을 덧붙입니다.

## 4. 성취기준과 유형으로 찾기

```powershell
python scripts/math_assessment_research.py standards --curriculum 2022 --subject "기하" --semester 2 --limit 5
python scripts/math_assessment_research.py standards --curriculum 2022 --subject "기하" --standard "12기하01-01" --semester 2 --limit 5 --offset 5
python scripts/math_assessment_research.py references --curriculum 2022 --subject "공통수학2" --category modeling --limit 3
```

`standards`는 공식 성취기준 문장과 연결 과제 목록을 제공합니다. **현재 API는 2026학년도 자료에 고정**돼 있습니다. 코드를 생략하면 API가 연결된 기준 하나를 선택합니다. `selected_standard`를 확인하고 `standard_options`에서 다른 기준을 골라 다시 조회하세요. 과제 전체를 읽으려면 목록의 ID로 `item` 또는 `bundle`을 실행합니다.

성취기준 등록 범위는 2015·2022 개정의 25개 교육과정·과목 조합, 453개 기준입니다. 2015 개정 「인공지능 수학」의 13개 기준은 교육부 고시 제2020-236호에서 추가했습니다. 두 교육과정에 같은 `[12인수01-01]` 코드가 있어도 공식 문장은 다르므로, 과목명이나 코드만 보고 교육과정을 합치지 않습니다. 연결 자료가 어느 교육과정인지 확인되지 않으면 판별 유보로 남깁니다. [성취기준 비교 안내](ACHIEVEMENT_STANDARD_COMPARISON.md)에서 범위와 공식 근거를 확인할 수 있습니다. 새 등록분의 운영 제공 여부는 실제 조회 결과와 배포 상태를 함께 확인하세요.

`references`는 탐구(`inquiry`), 모델링(`modeling`), 문제해결(`problem`), 발표(`presentation`), 포트폴리오(`portfolio`), 독서(`reading`)의 참고 목록입니다. 이 API는 학년도·학기·검색어·offset을 지원하지 않습니다. 기간이 중요하면 `search`/`bundle`을 사용하세요. 정렬은 필요한 근거가 확인되는 순서이며 설계 품질이나 학교 순위가 아닙니다.

## 5. 출력 범위를 먼저 읽기

| 필드 | 뜻 |
| --- | --- |
| `query` / `retrieved_at` | 실제 조건과 조회 시각 |
| `scope.matched_total` / `matched_total_unit` | 이 검색의 일치 수와 단위. 전국 개설 수가 아님 |
| `scope.returned_count` / `returned_unit` | 반환된 사례 또는 과제 수 |
| `scope.retrieved_items_count` | bundle에서 상세를 실제로 읽은 과제 수 |
| `scope.offset` / `offset_unit` | 건너뛴 단위. search/bundle은 사례, standards는 과제 |
| `scope.item_cap` | bundle의 상세 과제 상한 |
| `scope.omitted_candidate_items_on_this_page` | 이번 사례 페이지에서 상한 때문에 읽지 않은 과제 수 |
| `scope.truncated` / `more_after_this_page` | 일부만 가져왔는지, 뒤에 결과가 남는지 |
| `fetch_errors` / `scope.retrieval_complete` | 부분 실패. 실패한 자료를 빈 결과로 해석하면 안 됨 |
| `catalog_snapshot` | 조회 시 공개 아카이브 규모. 이번에 읽은 양과 구분 |
| `requests` | 실제 호출한 공개 GET 주소 |

기본 상한은5, 명시적 상한은1~30입니다. 다음 페이지가 필요할 때만 `--offset 5`처럼 지정하세요. 한 페이지를 전국 표본이나 전국 경향으로 일반화하지 않습니다. 사례 검색의 `--query`는 사례 텍스트 검색이며 개별 과제명이 그 단어와 정확히 일치한다는 뜻은 아닙니다. 교육과정 판별 유보는 기본 제외하며 필요할 때 `--include-ambiguous`를 지정합니다.

학기 `unknown`은 API의 학년도·학기 미확인 분류입니다. 임의로1학기나2학기로 바꾸지 않습니다. 미검출·추출 실패·개설 여부 미확인을 미개설로 바꾸지 않습니다.

## 6. 비교와 재설계

`research/prompts/`에8개의 시작 질문이 있습니다. 같은 기준의 과제 비교, 채점 단계 대조, 공통수학 과목 간 활동 연결, 수업시간에 맞춘 재설계, AI 사용 조건 검토 등에 쓸 수 있습니다.

답변은 원문에서 확인한 사실, 해석과 한계, 우리 수업에 맞춘 새 제안을 구분해 달라고 요청하세요. PUA 경고·수식 이상·빈 채점표가 있으면 원문 그림과 공식 파일부터 확인합니다. 그림을 보지 못한 AI가 수식을 고치거나 점수를 채우게 하지 마세요. 2028 대입 정책과 대학 선호는 이 사례 자료만으로 단정할 수 없습니다.

## 7. 결과 보관과 다른 AI 도구

출력은 기본적으로 화면에만 나타납니다. `--output`을 지정하면 새 UTF-8 JSON 파일을 만들고 기존 파일은 덮어쓰지 않습니다. **실제 학교 조회 결과는 개인 연구용 `research/outputs/`에 보관하고 GitHub에 커밋하지 않습니다.** 공개 저장소에는 코드·질문·가상 예제만 둡니다. 운영 DB·학교 원문·학생 자료·개인 토큰도 올리지 않습니다.

웹 ChatGPT나 다른 AI 채팅에서는 이 폴더의 AGENTS.md가 자동 적용된다고 가정하지 않습니다. 교사가 실행한 JSON과 필요한 원문 그림을 첨부하고, `research/AGENTS.md`의 연구 지침을 함께 전달하세요. MCP를 사용할 때는 [연결 안내](MCP_CONNECTION.md)의 운영 확인 상태와 해당 AI 도구의 지원 범위를 먼저 확인합니다. MCP 구현·로컬 검증, 내 도구에 주소 등록, 실제 공개 서버 조회 성공은 각각 확인해야 합니다.

연결 실패는 네트워크·공개 API 상태를 확인하고, HTTP404는 원문 정정/공개 보류나 잘못된 ID 가능성을 확인합니다. 결과가 없다는 이유로 학교가 과목을 개설하지 않았다고 판단하지 않습니다. API 점검 명령은 방문자 카운터나 분석 전송을 호출하지 않습니다.

## 8. MCP로 연결해 읽기

MCP에는 공개 범위 확인(`get_archive_scope`), 검색(`search_assessments`), 과제 상세(`get_assessment_item`), 공식 기준(`get_achievement_standards`), 2~4개 과제 비교(`compare_assessments`), 원문 그림 확인(`get_original_preview`)의 여섯 도구가 있습니다. 운영 주소에서 여섯 도구119검사, 공식25조합453기준의 코드·문장 대조와 실제 원문·채점표 그림 확인을 통과했습니다.

[MCP 연결 안내](MCP_CONNECTION.md)에 따라 개인 AI에 주소를 등록하고 `get_archive_scope`부터 실제 호출합니다. 도구가 등록됐다는 사실만으로 자료를 조회했다고 설명하지 않습니다. MCP가 기본으로 주는 범위·문자 상한과 CLI의 상한은 서로 다르므로 각 응답의 `scope`·잘림·부분 실패를 확인하세요. MCP도 실제 원문 그림을 읽지 못한 경우에는 확인하지 못했다고 밝혀야 합니다.
