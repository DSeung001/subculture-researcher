# Subculture Researcher

애니메이션·피규어·굿즈 관련 신제품/뉴스 정보를 자동/수동으로 수집해 Firestore에 저장하고, Flask 리뷰 앱에서 검토·분류하는 개인용 리서치 도구입니다.

## 핵심 기능

- `sources.yaml`에 등록된 공식/미디어 소스를 자동 수집 (`python collect.py`)
- 사용자 커뮤니티/포럼 글은 수집 대상에서 제외 (신규 상품 · 애니메이션 정보 · 피규어 정보만 유지)
- 같은 URL은 SHA-256 document ID로 중복 저장 방지
- 일본어·영어 등 외국어 제목은 MyMemory 무료 API로 한국어 번역(`titleKo`)을 함께 저장
- Flask 리뷰 앱(`python app.py`)에서 카테고리/티어/발행여부로 필터링하고, 채택 / 보류 / 무시로 분류
- X 등에서 발견한 게시물 URL을 리뷰 앱에서 수동으로 추가 저장

소스 목록과 수집 정책은 [source.md](./source.md), Firestore 필드 구조는 [agent.md](./agent.md)를 참고하세요.

## 실행 방법

### 1. 저장소 받기

```bash
git clone https://github.com/DSeung001/subculture-researcher.git
cd subculture-researcher
```

### 2. Python 환경 만들기

Python 3.11 이상을 권장합니다.

macOS / Linux:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. Firebase 설정

Firebase 프로젝트에서 Cloud Firestore를 활성화합니다.

Firebase Console에서 Service Account JSON 키를 발급하고 프로젝트 루트에 `firebase-key.json`으로 저장할 수 있습니다.

이 파일은 `.gitignore`에 포함되어 있으며 절대 GitHub에 커밋하면 안 됩니다.

macOS / Linux:

```bash
export GOOGLE_APPLICATION_CREDENTIALS="$PWD/firebase-key.json"
```

Windows PowerShell:

```powershell
$env:GOOGLE_APPLICATION_CREDENTIALS="$PWD\firebase-key.json"
```

### 4. 데이터 수집

```bash
python collect.py
```

`sources.yaml`의 활성화된 소스를 순서대로 수집합니다. HTML 소스는 `robots.txt` 확인에 실패하거나 자동 수집이 허용되지 않으면 건너뜁니다.

신규 항목의 제목(및 있는 경우 요약)이 한글이 아니면 MyMemory 무료 번역 API로 한국어를 만들어 `titleKo` / `summaryKo`에 저장합니다. 원문 제목은 그대로 두고, 리뷰 앱에서 번역을 먼저 보여 줍니다. 본문은 저장하지 않습니다.

선택적으로 이메일 주소를 넣으면 일일 한도가 5,000자에서 50,000자로 늘어납니다.

```bash
export MYMEMORY_EMAIL="you@example.com"
```

이미 저장된 외국어 항목에 번역이 없다면:

```bash
python collect.py --backfill-translations
```

`--dry-run`은 Firestore에 쓰지 않으므로 번역 API도 호출하지 않습니다.

### 5. 리뷰 앱 실행

```bash
python app.py
```

`http://127.0.0.1:5000`에서 로컬 전용으로 실행됩니다 (인증 없음, 외부에 공개하지 마세요).
