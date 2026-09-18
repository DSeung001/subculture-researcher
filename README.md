# Subculture Researcher

애니메이션·피규어·굿즈 관련 신제품/뉴스 정보를 자동/수동으로 수집해 Firestore에 저장하고, Flask 리뷰 앱에서 검토·분류하는 개인용 리서치 도구입니다.

## 핵심 기능

- `sources.yaml`에 등록된 공식/미디어 소스를 자동 수집 (`python collect.py`)
- 사용자 커뮤니티/포럼 글은 수집 대상에서 제외 (신규 상품 · 애니메이션 정보 · 피규어 정보만 유지)
- 같은 URL은 SHA-256 document ID로 중복 저장 방지
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

### 5. 리뷰 앱 실행

```bash
python app.py
```

`http://127.0.0.1:5000`에서 로컬 전용으로 실행됩니다 (인증 없음, 외부에 공개하지 마세요).
