# Subculture Researcher

애니메이션·게임의 **작품·IP별로 상품·예약·이벤트 정보를 모아 소개 글을 기획하는 개인용 앱**입니다. 클라우드에서 수집한 정보를 로컬 DB(PostgreSQL)로 내려받고, 작품 중심으로 제품 종류·시기를 좁혀 기획을 묶은 뒤 소재를 골라 바로 글로 씁니다.

흐름: **수집 → 동기화 → 작품 연결·분류 → 기획에 담기 → 글쓰기**. 인박스·AI 초안도 그대로 씁니다.

[개발 원칙](AGENTS.md) · [수집 대상·정책](source.md)

## 설정

Python 3.11+, 저장소 폴더에서 실행.

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
```

- 활성화가 안 되면 `.\.venv\Scripts\python.exe`를 매번 앞에 붙여 실행하세요. `python`이 아예 안 잡히면 실제 설치 경로로 가상환경을 새로 만드세요.
- Firestore를 활성화하고 서비스 계정 JSON을 저장소 루트에 `firebase-key.json`으로 저장.
- AI 초안을 쓰려면 `.env`에 `GEMINI_API_KEY=키값` 추가(없어도 수집·분류·기획은 가능).
- `firebase-key.json`, `.env`는 커밋 금지. Chromium은 `collect_manual.py`(로컬 브라우저 수집)에 필요.

## 명령어

Windows에서 가상환경 미활성화 시 `python`을 `.\.venv\Scripts\python.exe`로 바꾸세요.

| 작업 | 명령 |
|---|---|
| 앱 열기 (http://127.0.0.1:5001) | `python app.py` |
| 자동 수집 | `python collect.py` |
| AI 초안 없이 수집 | `python collect.py --no-ai-draft` (GitHub Actions는 항상 이 옵션) |
| 수집 캐시 무시 | `python collect.py --force-refresh --source "소스이름"` |
| 사진 없는 기존 문서 보완 | `python collect.py --backfill-images` |
| 수집 후 동기화 건너뛰기 | `python collect.py --no-sync` (`collect_manual.py`도 동일) |
| 수동 수집 (네이버 스토어, Playwright) | `python collect_manual.py` |
| 수동 소스 일부만 | `python collect_manual.py --source "소스이름"` |
| 클라우드 → 로컬 동기화 | `python sync_library.py` |
| 원격에서 사라진 로컬 항목 정리 | `python prune_library.py --dry-run` 후 `--dry-run` 없이 |
| AI 초안 작성 | `python draft.py` |
| 작품별 AI 초안 | `python draft.py --by-work` |
| 작품 사전 시드·자동 연결 | `python seed_works.py` (`--sync`: 미동기화 신규 항목까지) |
| 작품 링크 없는 항목 요약 | `python seed_works.py --unmatched` |
| 선택 항목 이미지 벌크 저장 | `python export_images.py --ids FIGURE:… / --work-id N / --collection-id N` (UI 「이미지 다운로드」와 동일) |
| Firestore 임시글 삭제 | `python delete_firestore_drafts.py --dry-run` 후 `--dry-run` 없이 (삭제 전 `.local/backups`에 JSON 백업) |

첫 화면은 작품·기획(`/inbox`는 인박스). 시작 순서: **작품·기획 → 클라우드에서 동기화 → 분류 사전**. `python seed_works.py`로 `work_catalog.yaml` 기준 작품 사전을 채우고 자동 연결한 뒤, 분류 사전에서 키워드를 다듬을 수 있습니다. 로컬 전용 앱이라 외부에 공개하지 않습니다.

**수집**: `collect.py`는 수동 전용 소스를 제외한 자동 소스만 돕니다. 신규 항목이 1건 이상이고 AI 키가 있으면 로컬 라이브러리 점수 순 혼합 초안을 자동으로 하나 만듭니다(Gemini 호출 2회: 후보 선정 + 작성; 신규 없으면 건너뜀). `collect_manual.py`는 네이버 스토어(코토부키야·메가하우스 몰)를 시크릿 Playwright 창에서 돌리며, 캡차는 사용자가 직접 풀고 목록만 읽습니다. 애니 본편 업로드 채널은 소스로 두지 않습니다.

**초안(글)**: 작품·기획에서 소재를 선택하면 「글 만들기」(제목만)/「AI로 글 쓰기」(Gemini 작성) 버튼으로 글 화면으로 이동합니다. 로컬 DB(`drafts`·`draft_items`)에만 저장(Firestore 아님). 글은 **본문**(상품 정보만, 링크 없음, 260자 권장)과 **댓글**(`상품 페이지 참고 ↓` + 상품명·URL)로 나뉘며, 댓글의 URL은 코드가 재료의 실제 링크로 조립합니다(AI는 이름만 붙임). 세 경로: 로컬 혼합 초안(`draft.py`/`collect.py`/버튼), 작품별 초안(`draft.py --by-work`, 링크된 항목만), 인박스 수동 선택.

**자동 실행**: GitHub Actions는 주 3회(월·수·금 08:00 KST) 수집만, 초안 없음(`--no-ai-draft`). Secrets: `FIREBASE_KEY`(서비스 계정 JSON), 선택적으로 `MYMEMORY_EMAIL`.

## 코드 구조

경계 컨텍스트별로 `subculture/` 아래에 묶고, 각 컨텍스트를 `domain`(순수 규칙) · `application`(유스케이스) · `infrastructure`(Firestore·DB·HTTP·Gemini) · `interface`(CLI·화면)로 나눕니다. 의존 규칙은 [AGENTS.md](AGENTS.md) "Code layout"과 `tests/test_architecture.py`가 지킵니다.

| 폴더 | 역할 |
|---|---|
| `subculture/collection/` | 수집: 소스 설정(`sources.yaml`), 수집기, Firestore 저장(`ContentStore`), 수집 CLI |
| `subculture/library/` | 작품·기획: 로컬 DB 모델·`Library`, 동기화·시드, 화면, 마이그레이션 CLI, `work_catalog.yaml` |
| `subculture/drafts/` | 글: 초안 규칙·저장소, AI 초안 선정, Gemini 작성기, 초안 CLI |
| `subculture/shared/` | 공용 커널: 콘텐츠 어휘·문서 ID, 이미지·URL 규칙, 표시 규칙, Firebase 클라이언트, 경로 |
| `subculture/web/` | Flask 앱(인박스·글·수집 목록·ERD), `templates/`, `static/` |
| `migrations/`, `postgres_migrations/`, `alembic.ini` | Alembic 이력(적용된 리비전이 있어 루트에 그대로 둠) |
| 루트 `*.py` | 위 명령을 그대로 쓰는 얇은 실행 래퍼 |

## 로컬 DB 관리

작품·기획 화면과 `sync_library.py`는 기본으로 Docker PostgreSQL을 씁니다.

- 처음 한 번: `.env.example`을 참고해 `POSTGRES_PASSWORD`를 설정하고

  ```bash
  docker compose up -d db
  docker compose run --rm tools python migrate_library.py upgrade
  ```

  Docker가 꺼져 있거나 비밀번호가 없으면 작품·기획 화면은 안내 페이지(503)를 보여줍니다.
- 스키마는 SQLAlchemy + Alembic. **앱·동기화를 끄고** 업그레이드하세요. 상태 확인 `docker compose run --rm tools`, 업그레이드 전 백업은 `.local/backups/`에 자동 생성(`pg_dump`).
- SQLite(레거시)는 `DATABASE_URL` 또는 `--db 경로`로 지정. 새 파일은 자동 초기화, 기존 파일은 `.bak` 백업 후 `migrate_library.py upgrade --db 경로`.
- 동기화는 매번 전체 항목을 읽고, 직접 지정한 분류·기획은 보존하며 원격에서 사라진 로컬 항목은 지우지 않습니다(정리는 `prune_library.py`로 따로). `collect.py`/`collect_manual.py`는 시작 시 동기화 상태를 보여주고(`--no-local-check`로 끔), 끝나면 기본으로 동기화합니다(`--no-sync`로 끔; CI는 둘 다 자동 생략).
- 인박스(Firestore 연결)는 기본으로 최근 14일 신규 항목만 표시, 「수집 기간」 칩으로 7일·30일·전체 전환(데이터는 안 바뀜).

## 테스트

```bash
python -m unittest discover -s tests -v
```

Windows에서 가상환경 미활성화 시 `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`.
