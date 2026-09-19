# Subculture Researcher

애니메이션·게임의 **작품·IP별로 상품·예약·이벤트 정보를 모아 소개 글을 기획하는 개인용 앱**입니다. 클라우드에서 수집한 정보를 로컬 DB(PostgreSQL)로 내려받고, 작품을 중심으로 제품 종류·시기를 좁혀 기획 묶음을 만들고, 소재를 골라 바로 글로 씁니다.

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
| AI 초안 없이 수집 | `python collect.py --no-ai-draft` (GitHub Actions는 항상 이 옵션) |
| Firestore에 남은 임시글 삭제 | `python delete_firestore_drafts.py --dry-run` 후 `--dry-run` 없이 실행 (삭제 전 `.local/backups`에 JSON 백업) |
| 클라우드 → 로컬 동기화 | `python sync_library.py` |
| 수집 후 동기화 건너뛰기 | `python collect.py --no-sync` (`collect_manual.py`도 동일) |
| 원격에서 사라진 로컬 항목 정리 | `python prune_library.py --dry-run` 후 `--dry-run` 없이 실행 |
| 수동 수집 (YouTube) | `python collect_manual.py` |
| 수동 소스 일부만 | `python collect_manual.py --source "소스이름"` |
| AI 초안 작성 | `python draft.py` |
| 작품별 AI 초안 | `python draft.py --by-work` |
| 작품 사전 시드·자동 연결 | `python seed_works.py` |
| 작품 링크 없는 항목 요약 | `python seed_works.py --unmatched` |
| 수집 캐시 무시 | `python collect.py --force-refresh --source "AniList 트렌딩 애니"` |
| 사진 없는 기존 문서 보완 | `python collect.py --backfill-images` |

Windows에서 가상환경을 활성화하지 않았다면 위 명령의 `python`을 `.\.venv\Scripts\python.exe`로 바꾸세요.

앱은 [http://127.0.0.1:5001](http://127.0.0.1:5001)에서 엽니다. **작품·기획 → 클라우드에서 동기화 → 분류 사전** 순서로 시작하고, 항목을 선택해 작품 연결이나 기획 담기를 합니다. 저장된 제목으로 작품 사전을 채우려면 `python seed_works.py`(`work_catalog.yaml`)를 실행한 뒤 분류 사전에서 키워드를 수정·자동 연결할 수 있습니다. 로컬 전용이므로 외부에 공개하지 않습니다.

자동 수집(`collect.py`)은 YouTube 등 수동 전용 소스를 제외합니다. 수동 수집은 `collect_manual.py`로 YouTube RSS만 돌립니다. 라프텔은 스토어(`store.laftel.net`) 공개 HTML이 자동 수집에 포함됩니다. 일반 자동 수집은 AI 키가 있으면 Firestore 점수 순 혼합 초안도 하나 만듭니다.

작품·기획에서 소재를 선택하면 화면 하단에 「글 만들기」(제목·링크 목록 초안, AI 없음)와 「AI로 글 쓰기」(Gemini가 본문 작성) 버튼이 나타나며, 누르면 글 화면의 새 글로 바로 이동합니다. 임시글은 Firestore가 아니라 **로컬 DB**(`drafts`·`draft_items`)에 저장되고, 글 화면에 재료의 사진이 함께 보입니다. 세 갈래로 만듭니다. (1) 로컬 `collect.py`·`draft.py`·「AI로 글 만들기」의 혼합 초안(수집 후 기본으로 로컬에 동기화되므로 새 수집분도 후보에 포함), (2) 동기화·작품 연결 후 `draft.py --by-work` 또는 「작품별로 글 만들기」로 피규어·애니·혼합을 같은 IP끼리 묶는 로컬 초안, (3) 인박스에서 직접 고르는 수동 초안.

GitHub Actions는 매일 08:00 KST에 자동 수집하고 혼합 초안도 만듭니다. 저장소 Secrets에 `FIREBASE_KEY`(서비스 계정 JSON 전체)를 넣고, 필요하면 `GEMINI_API_KEY`·`MYMEMORY_EMAIL`도 설정합니다.

## 로컬 DB 관리

작품·기획 화면과 `sync_library.py`는 기본적으로 Docker의 PostgreSQL을 사용합니다. 로컬에서 `collect.py`/`collect_manual.py`를 실행하면 시작할 때 로컬 동기화 상태(미동기화·로컬에만 남은 항목 수)를 Firestore 추가 읽기 없이 보여 줍니다(`--no-local-check`로 끔, `CI` 환경변수가 있으면 자동으로 건너뜀). 수집이 끝나면 **기본으로** Firestore → 로컬 동기화를 돌립니다(끄려면 `--no-sync`, GitHub Actions/`CI`에서는 자동으로 건너뜀). 동기화는 현재 전체 항목을 읽으며 직접 지정한 분류와 기획을 보존합니다. 기존 인박스·초안 화면은 Firestore에 연결합니다. 인박스는 기본으로 「새 항목」 중 **최근 14일** 수집분만 보여 주며, 「수집 기간」 칩에서 7일·30일·전체 기간으로 바꿉니다(데이터는 바꾸지 않습니다).

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
