# Subculture Researcher

애니메이션·피규어·굿즈·페스티벌 신제품/뉴스를 모아 Firestore에 저장하고, 브라우저 리뷰 앱에서 채택·보류·무시로 분류하는 개인용 도구입니다.

상세 정책: [source.md](./source.md) · 데이터 구조: [agent.md](./agent.md)

---

## 한 번에 보기

| 하고 싶은 일 | 명령 |
|---|---|
| 리뷰 앱 열기 | `python app.py` → http://127.0.0.1:5000 |
| 자동 수집 | `python collect.py` |
| 수동(브라우저) 수집 | `python collect.py --local-browser --source "소스이름"` |
| AI 임시글만 만들기 | `python draft.py` |

Windows에서는 가상환경이 켜져 있지 않으면 `python` 대신 `.\.venv\Scripts\python.exe` 를 쓰면 됩니다.

---

## 1. 처음 한 번만 설정

```bash
git clone https://github.com/DSeung001/subculture-researcher.git
cd subculture-researcher
```

Python 3.11 이상 권장.

### Windows (PowerShell)

```powershell
# python 이 안 되면 Windows Store 스텁일 수 있음 → 실제 설치 경로로 실행
# 예: & "$env:LOCALAPPDATA\Python\bin\python.exe" -m venv .venv
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
```

`Activate.ps1` 이 막히면:

```powershell
.\.venv\Scripts\activate.bat
```

활성화 없이 바로 쓰려면:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

`source .venv/bin/activate` 는 macOS/Linux 전용입니다. Windows에서는 쓰지 마세요.

### macOS / Linux

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

### Firebase · API 키

1. Firebase Console에서 Firestore 활성화
2. Service Account JSON을 프로젝트 루트에 `firebase-key.json` 으로 저장 (커밋 금지, `.gitignore` 됨)
3. (선택) AI 임시글용 키를 `.env`에 추가:

```bash
GEMINI_API_KEY=여기에_발급받은_키
```

키가 없어도 수집·리뷰 앱은 동작합니다. AI 초안 단계만 건너뜁니다.

---

## 2. 리뷰 앱

```bash
python app.py
```

Windows (활성화 안 했을 때):

```powershell
.\.venv\Scripts\python.exe app.py
```

브라우저에서 http://127.0.0.1:5000  
로컬 전용(인증 없음). 외부에 공개하지 마세요.

앱에서 URL을 직접 붙여 넣어 수동 추가도 가능합니다.

---

## 3. 자동 수집

RSS/HTML/API 등 `local_only`가 아닌 소스를 한꺼번에 수집합니다.  
로그인·Playwright 전용 소스는 **건너뜁니다**.

```bash
python collect.py
```

Windows:

```powershell
.\.venv\Scripts\python.exe collect.py
```

자주 쓰는 옵션:

```bash
python collect.py --dry-run                 # Firestore에 쓰지 않음
python collect.py --backfill-translations   # 기존 항목 번역 채우기
```

수집이 끝나면(dry-run 아닐 때) `GEMINI_API_KEY`가 있으면 임시글 초안을 하나 만듭니다.  
수집 없이 같은 초안만 다시 만들려면 `python draft.py`를 쓰면 됩니다.  
앱 드래프트 탭의 "AI로 글 만들기"로도 가능합니다. 세 경로 모두 같은 선정·작성 로직을 씁니다.

Gemini 무료 한도를 넘지 않도록 요청은 6.5초 이상 간격을 두고 보냅니다.  
429/5xx 응답은 서버가 알려준 대기 시간(없으면 5·10·20초)만큼 기다린 뒤 최대 3번 재시도하고,
일일 한도를 다 쓰면 그 실행에서는 더 호출하지 않습니다.  
AI 초안 없이 수집만 하려면 `--no-ai-draft`를 붙이세요.

```bash
python draft.py                  # 미게시 인박스로 초안 하나
python draft.py --category FIGURE  # 해당 카테고리만
```

번역 API 한도를 늘리려면:

```bash
# macOS / Linux
export MYMEMORY_EMAIL="you@example.com"

# Windows PowerShell
$env:MYMEMORY_EMAIL="you@example.com"
```

---

## 4. 수동 수집 (Playwright / 로컬 브라우저)

로그인·Cloudflare·JS 화면이 필요한 소스입니다.  
일반 `python collect.py` 와 GitHub Actions에서는 돌지 않습니다. **로컬에서만** 실행하세요.

첫 Chromium 설치(한 번):

```bash
python -m playwright install chromium
```

소스 하나 수집:

```bash
python collect.py --local-browser --source "라프텔 인기·신작"
```

Windows:

```powershell
.\.venv\Scripts\python.exe collect.py --local-browser --source "라프텔 인기·신작"
```

### 전체 소스 한 번에 수집

`local_only` 소스를 전부 순서대로 수집합니다. `--local-browser`가 포함되어 있고 `--source`와는 함께 쓸 수 없습니다.

```bash
python collect.py --all-local
```

소스마다 `[3/7] 소스 이름`이 출력되고 Chromium 창이 차례로 열립니다.  
각 소스에서 아래 진행 순서대로 로그인/화면 이동 후 터미널에서 **Enter**를 누르면 다음 소스로 넘어갑니다.  
한 소스가 실패해도 나머지는 계속 진행하며, AI 초안은 전체가 끝난 뒤 한 번만 만듭니다.

### 대상 소스

```bash
python collect.py --local-browser --source "라프텔 인기·신작"
python collect.py --local-browser --source "라프텔 스토어"
python collect.py --local-browser --source "animate 서울홍대점"
python collect.py --local-browser --source "일러스타 페스"
python collect.py --local-browser --source "코믹월드"
python collect.py --local-browser --source "Kotobukiya 뉴스"
python collect.py --local-browser --source "애니메이트 코리아 페어·이벤트"
```

### 진행 순서

1. 명령 실행 → Chromium 창이 열림
2. 로그인 / MFA / Cloudflare / 원하는 목록 화면까지 **직접** 처리
3. 터미널에서 **Enter**
4. 현재 화면을 스크롤하며 링크·메타데이터 수집

세션은 `.local/playwright/<프로필>`에 저장됩니다 (gitignore). 다음부터는 로그인이 덜 필요할 수 있습니다.

---

## 5. GitHub Actions (자동 수집만)

수·토 08:00 KST에 `collect.py`가 돕니다. Playwright 수동 소스는 포함되지 않습니다.

`firebase-key.json`은 커밋하지 말고, 파일 **내용**을 시크릿으로 넣습니다.

1. 저장소 → Settings → Secrets and variables → Actions
2. `FIREBASE_KEY` = JSON 전체 (`{` ~ `}`)
3. (선택) `MYMEMORY_EMAIL`, `GEMINI_API_KEY`

Actions 탭의 `Collect sources`로 수동 실행도 가능합니다.

---

## Windows에서 `python`이 안 될 때

에러: `python.exe` / `The system cannot find the path specified`

→ Microsoft Store용 `python` 스텁입니다. 실제 Python이 PATH 앞쪽에 없습니다.

해결:

1. [python.org](https://www.python.org/downloads/)에서 설치 후 **"Add python.exe to PATH"** 체크, 또는
2. 전체 경로로 venv 만들기:

```powershell
& "$env:LOCALAPPDATA\Python\bin\python.exe" -m venv .venv
.\.venv\Scripts\Activate.ps1
```

이후에는 `.\.venv\Scripts\python.exe` 로 앱·수집을 실행하면 됩니다.
