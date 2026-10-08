# Subculture Researcher

애니메이션·게임의 상품·예약·이벤트 정보를 매일 모아 **작품·IP별로 보여주는 개인용 리서치 도구**입니다.

**수집(GitHub Actions, 매일 08:00 KST) → Firestore → 보기 전용 사이트(GitHub Pages)**

**[사이트 바로가기](https://dseung001.github.io/subculture-researcher/)** — 화면 폭에 맞춰 여러 열로 표시되는 카드 그리드에서 한 번에 60개씩 볼 수 있습니다.

[개발 원칙](AGENTS.md) · [수집 대상·정책](source.md)

## 설정

Python 3.11+

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium   # 수동 수집에만 필요
```

Firestore 서비스 계정 JSON을 저장소 루트에 `firebase-key.json`으로 둡니다. 이 파일과 `.env`는 커밋하지 않습니다.

## 명령어

| 작업 | 명령 |
|---|---|
| 검토 화면 열기 (http://127.0.0.1:5001) | `python app.py` |
| 자동 수집 | `python collect.py` |
| 수동 수집 (네이버 스토어) | `python collect_manual.py` |
| 사이트 만들기 | `python build_site.py` |
| 만든 사이트 미리보기 (http://localhost:8000) | `python -m http.server -d site` |
| 테스트 | `python -m unittest discover -s tests -v` |

그 밖의 수집 옵션과 정리 명령은 [source.md](source.md)에 있습니다.

## 화면

- **사이트** (배포, 보기 전용): 수집한 항목을 작품·IP, 카테고리, 수집 출처, 기간, 검색어로 걸러 봅니다. 작품은 한글·영문·일문 별칭으로, 수집 출처는 이름으로 검색해 선택할 수 있습니다.
- **검토 화면** (로컬 전용): 항목을 채택·보류·무시로 표시하고 메모를 남기거나 URL을 직접 추가합니다. 「무시」한 항목은 다음 배포부터 사이트에서 빠집니다. 여러 항목을 체크하고 「비교글 만들기」를 누르면 X에 올릴 본문(비교 정보)과 댓글(링크)이 같은 검토 화면 안에 만들어집니다. 편집한 뒤 복사하거나 「X에서 열기」로 본문 작성창을 열고, 링크 댓글은 직접 답글로 붙입니다. 선택과 글은 현재 페이지에서만 유지되며 새로고침하면 초기화됩니다.

## 작품·IP 분류

`subculture/library/work_catalog.yaml`의 작품명·별칭이 항목 제목에 들어 있으면 그 작품으로 묶입니다. 분류를 고치려면 yaml에 작품이나 별칭을 추가하고 다시 배포합니다. 어디에도 안 잡힌 항목은 사이트의 「작품 미분류」에서 볼 수 있습니다.

## 배포

수집이 끝나면 자동으로 다시 배포됩니다. 로컬에서 수집했거나 yaml을 고쳤다면 직접 실행합니다([GitHub CLI](https://cli.github.com/) 필요).

| 작업 | 명령 |
|---|---|
| 지금 다시 배포 | `gh workflow run "Deploy site"` |
| 배포 진행 보기 | `gh run watch` |
| 사이트 주소 확인 | `gh api repos/{owner}/{repo}/pages --jq .html_url` |
| 사이트 열기 | `open "$(gh api repos/{owner}/{repo}/pages --jq .html_url)"` |

처음 한 번만: 저장소를 public으로 두고 Settings → Pages → Source를 **GitHub Actions**로 설정, Secrets에 `FIREBASE_KEY`(서비스 계정 JSON)를 넣습니다.

사이트 주소를 아는 사람은 수집 목록을 모두 볼 수 있습니다. 키는 Actions에만 있고 페이지에는 포함되지 않습니다.
