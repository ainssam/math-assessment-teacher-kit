# 수학 수행평가 아이디어 아카이브

다른 학교의 수행평가 계획을 읽고, 우리 수업에 맞는 과제와 채점기준을 설계하는 데 쓰는 교사용 웹앱입니다. 과목별 사례 검색, 원문 표 보기, 사례 비교에 쓰인 웹·API 코드와 학교알리미 4-가 자료 처리 방법을 함께 공개합니다. [운영 중인 아카이브](https://suhaeng-math.vercel.app/cases)

[이번 업데이트 상세 내역](docs/UPDATE_REPORT_2026_SECOND_SEMESTER.md) · [2026학년도 자료 범위와 검증 기준](docs/SCHOOLINFO_2026_DATA_INDEX.md)

## 내 AI에게 자료 조사를 부탁하기

**ChatGPT·Claude를 쓰는 선생님은 [코딩 없이 연결하는 상세 사용법](docs/TEACHER_AI_GUIDE.md)부터 보세요.**

| 사용하는 AI | 연결 안내 |
| --- | --- |
| ChatGPT | [플러그인에 MCP 추가 → 새 대화에서 선택 → 첫 조회](docs/CHATGPT_MCP_GUIDE.md) |
| Claude | [맞춤 커넥터 추가 → 대화에서 켜기 → 첫 조회](docs/CLAUDE_MCP_GUIDE.md) |

각 안내에는 입력값, 무료·개인·학교 조직 계정에서 확인할 점, 오류 해결, 해제 방법을 담았습니다. 공통 안내의 질문을 복사해 성취기준 비교·1학기 자료 조사·우리 반 수행평가 재설계에 쓸 수 있습니다. 공식 제품 문서 확인 기준은 2026년 11월 9일이며 계정별 메뉴 제공과 사용량 한도는 적용됩니다.

앱을 직접 설치하지 않아도 공개 아카이브를 조회할 수 있습니다. **원격 MCP를 지원하는 개인 AI 도구**에 아래 주소를 연결하면 자료 범위 확인, 학년도·학기·과목·지역 검색, 과제 상세, 공식 성취기준, 2~4개 과제 비교, 검증된 원문 그림 조회를 사용할 수 있습니다.

```text
https://suhaeng-math.vercel.app/api/mcp
```

인증 방식은 **없음 / No authentication**, 전송 방식은 **Streamable HTTP**입니다. 개인 AI 로그인이나 구독 정보는 이 서버에 입력하지 않습니다. AI는 자신의 계정에서 답변을 작성하고 MCP는 공개 근거를 읽어 전달합니다. 각 AI 서비스의 기능 제공 범위와 사용 한도가 적용됩니다. [MCP 연결 방법과 문제 해결](docs/MCP_CONNECTION.md)

Codex CLI에서는 다음과 같이 연결할 수 있습니다.

```powershell
codex mcp add suhaeng-math --url https://suhaeng-math.vercel.app/api/mcp
```

연결한 뒤 이렇게 요청해 보세요.

> 수학 수행평가 MCP로 2026학년도 2학기, 2022 개정 기하 사례를 최대5개 찾아줘. 그중 두 과제의 실제 수행 내용과 채점표를 읽어 비교하고, 학교·학기·공식 출처를 붙여줘. 검색 일치 수와 실제로 읽은 수를 구분하고, 원문 확인 메모도 알려줘. 수식이 이상하면 원문 그림을 확인해줘.

MCP 연결을 지원하지 않으면 **Python만으로 실행하는 공개 조회 도구**를 사용할 수 있습니다. 저장소의 `research` 폴더를 Codex로 열어 질문하거나, 명령 결과를 AI에 첨부하면 됩니다. [개인 AI 연구 안내·명령 예시](docs/AI_RESEARCH_GUIDE.md) · [시작 질문8개](research/prompts/)

이 저장소를 AI에게 읽히는 것만으로 운영 자료가 자동 검색되지는 않습니다. MCP 또는 조회 도구를 실제로 실행해야 최신 자료를 확인할 수 있습니다. 두 경로 모두 자료 수정·학생 평가·자동 게시 기능은 없으며, 교사가 원문을 대조하고 수업 조건에 맞게 판단합니다.

## 처음 실행하기

Node.js 24 이상, pnpm 11, Python 3.12 이상이 필요합니다. 아래 예시는 Windows PowerShell 기준입니다. GitHub에서 **Code → Download ZIP**으로 받은 경우에는 압축을 풀고 그 폴더에서 `pnpm install`부터 실행하면 됩니다.

Windows에서 프로젝트를 외장 드라이브에 둘 때는 NTFS를 사용하세요. exFAT에서는 pnpm의 의존성 링크 설치가 실패할 수 있습니다.

```powershell
git clone https://github.com/ainssam/math-assessment-teacher-kit.git
cd math-assessment-teacher-kit
pnpm install --frozen-lockfile
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r services/math-assessment-api/requirements.txt
.\.venv\Scripts\python.exe -m scripts.build_math_assessment_demo
$env:MATH_ASSESSMENT_PUBLISH_DB = (Resolve-Path data/demo/demo.sqlite).Path
$env:MATH_ASSESSMENT_DETAIL_DB = $env:MATH_ASSESSMENT_PUBLISH_DB
pnpm dev
```

터미널을 열어 둔 상태에서 [사례 탐색](http://127.0.0.1:3100/cases)을 엽니다. **가상 예제 고등학교**의 대수 사례에서 제목을 누르면 평가 개요, 반영 비율, 채점기준 표를 볼 수 있습니다. 홈의 집계와 자료 안내에는 원본 앱의 운영 당시 설명이 표시됩니다. 예제로 생성한 DB에는 가상 사례 한 건이 있습니다. 종료할 때는 터미널에서 `Ctrl+C`를 누릅니다.

공유판의 방문자 집계와 웹 분석은 기본으로 꺼져 있습니다. 별도 사이트에서 사용하려면 그 사이트의 설정을 직접 지정합니다. [환경변수 예시](.env.example)

macOS·Linux에서는 `py -3.12`를 `python3.12`로, `.\.venv\Scripts\python.exe`를 `.venv/bin/python`으로 바꿉니다. 환경변수는 아래처럼 지정합니다.

```bash
export MATH_ASSESSMENT_PUBLISH_DB="$PWD/data/demo/demo.sqlite"
export MATH_ASSESSMENT_DETAIL_DB="$MATH_ASSESSMENT_PUBLISH_DB"
pnpm dev
```

## 전과목 협업에 참여하기

수학에서 쓰는 검색·필터, 원문 표, 비교 화면과 MCP를 바탕으로 다른 교과도 함께 준비합니다. 오류 제보나 한 과목의 평가 유형 정리부터 참여할 수 있습니다.

[기여 방법](CONTRIBUTING.md) · [일반 제보](https://github.com/ainssam/math-assessment-teacher-kit/issues) · [비공개 보안 신고](SECURITY.md)

## 자기 교과 자료로 적용하기

| 하고 싶은 일 | 읽을 곳 |
| --- | --- |
| 평가계획 몇 개로 추출 과정을 먼저 확인 | [수집·추출 따라 하기](docs/SCHOOLINFO_WORKFLOW.md) |
| 국어·사회·과학 등 다른 교과로 확장 | [교과를 바꿀 때 확인할 기준](docs/OTHER_SUBJECT_ASSESSMENT_VALIDATION_HANDOFF_2026-08-15.md) |
| 사례 화면·검색·비교 로직 읽기 | `apps/math-assessment-web/app/` |
| 검색 API와 DB 연결 읽기 | `services/math-assessment-api/app/` |
| 제목, 과목 경계, 배점, 원문 표의 검증 로직 읽기 | `scripts/`의 수집·추출·감사 코드 |

## 추출 코드를 수정한 뒤 확인하기

아래 테스트는 저장소의 가상 입력만으로 과목명, 수행평가 제목, 배점, 표 구조를 점검합니다. 운영 사례 수와 출처를 대조하는 테스트에는 별도로 수집한 DB가 필요합니다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r services/math-assessment-api/requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q services/math-assessment-api/tests/test_publish_builder.py services/math-assessment-api/tests/test_detail_parser.py
```

## 이용 범위와 도움 요청

이 저장소의 자체 소스코드, 안내 문서, 가상 예제는 MIT 라이선스로 이용할 수 있습니다. 의존 패키지의 권리는 각 패키지 라이선스를 따릅니다. 운영 서비스의 학교 자료와 데이터베이스는 별도로 관리합니다. [MIT 라이선스](LICENSE) · [출처와 공개 기준](docs/SOURCE_POLICY.md)

설치 중 막히면 GitHub Issues에 사용 중인 운영체제, Node.js와 Python 버전, 실행 명령과 오류 메시지를 남겨 주세요. 학교 첨부파일이나 API 키는 첨부하지 말아 주세요. 추출 오류를 문의할 때는 학교알리미 출처 링크와 문제의 표 위치를 알려 주시면 확인하기 쉽습니다.
