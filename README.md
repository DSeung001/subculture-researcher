# Subculture Researcher

애니메이션·게임의 **작품·IP별로 상품·예약·이벤트 정보를 모아 보는 개인용 리서치 도구**입니다. GitHub Actions가 매일 수집해 Firestore에 저장하고, 수집이 끝나면 작품·IP별로 분류한 **보기 전용 정적 사이트**를 GitHub Pages에 배포합니다.

흐름: **수집(Actions) → Firestore → 정적 사이트 빌드(작품 키워드 매칭) → GitHub Pages**. 항목 상태 변경·수동 추가는 로컬 인박스에서 합니다.

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
- `firebase-key.json`, `.env`는 커밋 금지. Chromium은 `collect_manual.py`(로컬 브라우저 수집)에 필요.

## 명령어

Windows에서 가상환경 미활성화 시 `python`을 `.\.venv\Scripts\python.exe`로 바꾸세요.

| 작업 | 명령 |
|---|---|
| 로컬 인박스 열기 (http://127.0.0.1:5001) | `python app.py` |
| 자동 수집 | `python collect.py` |
| 사진 없는 기존 문서 보완 | `python collect.py --backfill-images` |
| 수동 수집 (네이버 스토어, Playwright) | `python collect_manual.py` |
| 수동 소스 일부만 | `python collect_manual.py --source "소스이름"` |
| 정적 사이트 만들기 (Firestore 전체 1회 읽기) | `python build_site.py` (`--out 폴더`, 기본 `site/`) |
| 만든 사이트 미리보기 | `python -m http.server -d site` |
| 제목 없음 잔여 문서 정리 | `python delete_untitled_x.py --dry-run` 후 `--dry-run` 없이 |

**수집**: `collect.py`는 수동 전용 소스를 제외한 자동 소스만 돕니다. `collect_manual.py`는 네이버 스토어(코토부키야·메가하우스 몰)를 시크릿 Playwright 창에서 돌리며, 캡차는 사용자가 직접 풀고 목록만 읽습니다. 애니 본편 업로드 채널은 소스로 두지 않습니다.

**작품·IP 분류**: `subculture/library/work_catalog.yaml`의 작품명·별칭이 항목 제목(`title`·`titleKo`)에 들어 있으면 그 작품으로 묶습니다. 저장하지 않고 사이트를 만들 때마다 다시 계산하므로, 분류를 고치려면 yaml에 작품·별칭을 추가하고 다시 배포하면 됩니다. 어느 작품에도 안 잡힌 항목은 사이트의 「작품 미분류」 필터로 볼 수 있습니다.

**로컬 인박스**: Firestore에 직접 연결해 상태(채택·보류·무시)·발행 표시·메모를 바꾸고 URL을 수동 추가합니다. 「무시」한 항목은 다음 배포부터 사이트에서 빠집니다. 기본으로 최근 14일 신규 항목만 표시하며 「수집 기간」 칩으로 바꿉니다. 로컬 전용이라 외부에 공개하지 않습니다.

## 배포 (GitHub Pages)

- `Collect sources`(매일 08:00 KST)가 끝나면 `Deploy site`가 `python build_site.py`로 `data.json`과 페이지를 만들어 Pages에 올립니다. 로컬에서 수집했거나 yaml을 고친 뒤에는 Actions에서 `Deploy site`를 수동 실행하세요.
- 페이지는 Firestore에 연결하지 않습니다. 서비스 계정 키는 Actions secret에만 있고, 브라우저에는 빌드된 파일만 갑니다. 읽기 전용이며 하루 한 번(또는 수동 실행 시) 갱신됩니다.
- 처음 한 번: 저장소 Settings → Pages → Source를 **GitHub Actions**로 설정. 무료 플랜은 저장소가 public이어야 합니다.
- Secrets: `FIREBASE_KEY`(서비스 계정 JSON), 선택적으로 `MYMEMORY_EMAIL`.
- 사이트 주소를 아는 사람은 수집 목록(제목·링크·사진 주소·가격)을 모두 볼 수 있습니다. 검색엔진에는 `noindex`로 표시합니다.
- 빌드마다 Firestore 문서 전체를 한 번 읽습니다(무료 한도 하루 5만 읽기 기준으로 관리).

### 배포된 사이트 보기

주소는 `https://<GitHub 사용자명>.github.io/subculture-researcher/` 입니다. [GitHub CLI](https://cli.github.com/)(`gh auth login` 완료)로 확인·실행할 수 있습니다.

| 작업 | 명령 |
|---|---|
| 사이트 주소 확인 | `gh api repos/{owner}/{repo}/pages --jq .html_url` |
| 브라우저로 열기 | `open "$(gh api repos/{owner}/{repo}/pages --jq .html_url)"` (Windows: 출력된 주소를 `start`로) |
| 지금 다시 배포 | `gh workflow run "Deploy site"` |
| 배포 진행 지켜보기 | `gh run watch` |
| 최근 배포 결과 | `gh run list --workflow "Deploy site" --limit 5` |
| 배포된 데이터 시각·건수 확인 | `curl -s "$(gh api repos/{owner}/{repo}/pages --jq .html_url)data.json" \| python -c "import json,sys; d=json.load(sys.stdin); print(d['builtAt'], len(d['items']))"` |

`{owner}/{repo}`는 저장소 폴더 안에서 실행하면 `gh`가 자동으로 채웁니다. 배포 전에 같은 화면을 로컬에서 보려면 `python build_site.py` 후 `python -m http.server -d site`로 http://localhost:8000 을 엽니다.

## 코드 구조

경계 컨텍스트별로 `subculture/` 아래에 묶습니다. 의존 규칙은 [AGENTS.md](AGENTS.md) "Code layout"과 `tests/test_architecture.py`가 지킵니다.

| 폴더 | 역할 |
|---|---|
| `subculture/collection/` | 수집: 소스 설정(`sources.yaml`), 수집기, Firestore 저장(`ContentStore`), 수집 CLI |
| `subculture/library/` | 작품·IP 사전: `work_catalog.yaml`, 로더(`application/catalog.py`), 키워드 매칭(`domain/keywords.py`) |
| `subculture/shared/` | 공용 커널: 콘텐츠 어휘·문서 ID, 이미지·URL 규칙, 표시 규칙, Firebase 클라이언트, 경로 |
| `subculture/web/` | 로컬 Flask 앱(인박스·수집 목록), 정적 사이트 빌더(`site_builder.py`, `site/`), `templates/`, `static/` |
| 루트 `*.py` | 위 명령을 그대로 쓰는 얇은 실행 래퍼 |

## 테스트

```bash
python -m unittest discover -s tests -v
```

Windows에서 가상환경 미활성화 시 `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`.
