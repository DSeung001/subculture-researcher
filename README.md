# Subculture Researcher

애니메이션·게임의 **작품·IP별로 상품·예약·이벤트 정보를 모아 소개 글을 기획하는 개인용 앱**입니다. 클라우드에서 수집한 정보를 로컬 DB(PostgreSQL)로 내려받고, 작품을 중심으로 제품 종류·태그·시기를 좁혀 기획 묶음을 만듭니다.

사용 흐름: **수집 → 동기화 → 작품 연결·분류 → 기획에 담기**. 기존 인박스와 AI 초안 작성도 사용할 수 있습니다.

[개발 원칙](AGENTS.md) · [수집 대상·정책](source.md)

## 처음 설정

Python 3.11 이상을 권장합니다. 저장소 폴더에서 실행하세요.

### Windows (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
```

활성화가 막히면 활성화 없이 실행할 수 있습니다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe app.py
```

`python`이 실행되지 않으면 실제 설치된 Python의 전체 경로로 가상환경을 만드세요. 예:

```powershell
& "$env:LOCALAPPDATA\Python\bin\python.exe" -m venv .venv
```

이미 있는 `.venv`가 없어진 Python 경로를 가리키면 현재 설치된 Python으로 가상환경을 다시 구성해야 합니다. `source .venv/bin/activate`는 Windows 명령이 아닙니다.

### macOS / Linux

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m playwright install chromium
```

### 연결 설정

- Firestore를 활성화하고 서비스 계정 JSON을 프로젝트 루트의 `firebase-key.json`으로 저장합니다.
- AI 초안을 쓰려면 `.env`에 `GEMINI_API_KEY=키값`을 추가합니다. AI 키 없이도 수집·분류·기획은 가능합니다.
- 키 파일과 `.env`는 커밋하지 않습니다. Chromium은 로컬 브라우저 수집에 필요합니다.

## 실행

| 작업 | 명령 |
|---|---|
| 앱 열기 | `python app.py` |
| 자동 수집 | `python collect.py` |
| AI 초안 없이 수집 | `python collect.py --no-ai-draft` |
| 클라우드 → 로컬 동기화 | `python sync_library.py` |
| 로컬 브라우저 수집 | `python collect.py --local-browser --source "소스이름"` |
| 모든 로컬 소스 수집 | `python collect.py --all-local` |
| AI 초안 작성 | `python draft.py` |

Windows에서 가상환경을 활성화하지 않았다면 위 명령의 `python`을 `.\.venv\Scripts\python.exe`로 바꾸세요.

앱은 [http://127.0.0.1:5001](http://127.0.0.1:5001)에서 엽니다. **작품·기획 → 클라우드에서 동기화 → 분류 사전** 순서로 시작하고, 항목을 선택해 작품 연결이나 기획 담기를 합니다. 로컬 전용이므로 외부에 공개하지 않습니다.

자동 수집은 로컬 브라우저 전용 소스를 제외합니다. 브라우저 수집에서는 직접 로그인·화면 이동을 마친 뒤 터미널에서 Enter를 누릅니다. 일반 수집은 AI 키가 있으면 초안도 생성합니다.

GitHub Actions는 수·토 08:00 KST에 자동 수집합니다. 저장소 Secrets에 `FIREBASE_KEY`(서비스 계정 JSON 전체)를 넣고, 필요하면 `GEMINI_API_KEY`·`MYMEMORY_EMAIL`도 설정합니다.

## 로컬 DB 관리

작품·기획 화면과 `sync_library.py`는 기본적으로 Docker의 PostgreSQL을 사용합니다. 동기화는 현재 전체 항목을 읽으며 직접 지정한 분류와 기획을 보존합니다. 기존 인박스·초안 화면은 Firestore에 연결합니다.

처음 한 번: `.env.example`을 참고해 `.env`에 `POSTGRES_PASSWORD`를 설정하고 DB를 시작·초기화합니다. Docker가 꺼져 있거나 비밀번호가 없으면 작품·기획 화면은 안내 페이지(503)를 보여줍니다.

```bash
docker compose up -d db
docker compose run --rm tools python migrate_library.py upgrade
```

SQLAlchemy ORM과 Alembic으로 스키마를 관리합니다. **앱·동기화를 종료한 뒤** 기존 DB를 업그레이드하세요. 상태 확인은 `docker compose run --rm tools`(= `migrate_library.py current`)입니다. 업그레이드 전 백업은 `.local/backups/`에 `pg_dump`로 생성됩니다.

`DATABASE_URL` 환경변수나 `--db` 옵션으로 SQLite 파일 경로(레거시)를 지정할 수도 있습니다. 새 SQLite 파일은 자동 초기화되고, 기존 파일은 같은 폴더에 `.bak` 백업을 만든 뒤 `migrate_library.py upgrade --db 경로`로 업그레이드합니다.

## 테스트

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

가상환경 활성화 후에는 `python -m unittest discover -s tests -v`로도 실행할 수 있습니다.
