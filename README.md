# 수학 수행평가 아이디어 아카이브

다른 학교의 수행평가 계획을 읽고, 우리 수업에 맞는 과제와 채점기준을 설계하는 데 쓰는 교사용 웹앱입니다. 과목별 사례 검색, 원문 표 보기, 사례 비교에 쓰인 웹·API 코드와 학교알리미 4-가 자료 처리 방법을 함께 공개합니다. [운영 중인 아카이브](https://suhaeng-math.vercel.app/cases)

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
