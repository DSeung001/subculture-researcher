# Subculture Researcher

애니메이션, 피규어, 굿즈, 컬렉션 관련 정보를 자동/수동으로 수집하고 Firestore에 저장한 뒤 Streamlit에서 검토하는 개인용 리서치 도구입니다.

이 프로젝트의 목적은 **FiguRoom의 SNS 콘텐츠를 만들기 전에 어떤 주제와 포맷이 반복적으로 가치가 있는지 빠르게 확인하는 것**입니다.

## 컨셉

```
공식 사이트 / 커뮤니티 / 수동 URL
              ↓
        Python Collector
              ↓
           Firestore
              ↑
          Streamlit
              ↓
      채택 / 보류 / 무시
```

별도 API 서버를 두지 않습니다.

- Collector는 로컬 Python 프로세스로 실행합니다.
- 수집 데이터는 Firebase Firestore에 저장합니다.
- Streamlit은 Firestore 데이터를 조회하고 분류합니다.
- 같은 URL은 SHA-256 document ID를 사용해 중복 저장하지 않습니다.
- X는 직접 스크래핑하지 않고 필요한 게시물을 수동으로 저장합니다.

## 목적

초기에는 아래 질문에 답하는 데 집중합니다.

1. 국내외 서브컬처에서 어떤 이야기가 반복적으로 등장하는가?
2. 애니, 캐릭터, 피규어, 장식장 중 어떤 주제가 콘텐츠 후보로 많이 나오는가?
3. 어떤 항목을 실제 X 콘텐츠로 채택하게 되는가?
4. 이후 게시 성과와 연결했을 때 어떤 주제 × 포맷 조합이 좋은가?

현재는 콘텐츠 수집과 검토까지만 구현합니다.

## 현재 수집 대상

자동 수집 대상으로 설정된 소스는 `sources.yaml`에서 관리합니다.

- HOBBY Watch 피규어
- Good Smile Company 뉴스
- 애니플러스 뉴스
- DC 피규어 마이너 갤러리
- 루리웹 피규어 정보
- 덕벤 프라모델/피규어

X 중심 채널은 자동 스크래핑하지 않습니다.

- 라프텔
- animate 서울홍대점
- AGF Korea
- 일러스타 페스
- 코믹월드

자세한 수집 정책은 [source.md](./source.md)를 참고하세요.

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

실행 시 `sources.yaml`의 활성화된 소스를 순서대로 확인합니다.

HTML 소스는 `robots.txt` 확인에 실패하거나 자동 수집이 허용되지 않으면 건너뜁니다.

### 5. 대시보드 실행

```bash
streamlit run app.py
```

브라우저에서 다음 작업을 할 수 있습니다.

- 최신 수집 항목 확인
- 카테고리 필터
- 채택 / 보류 / 무시
- X 등에서 찾은 URL 수동 추가

## Firestore 구조

```
contents/{sha256(url)}
  url
  title
  summary
  source
  sourceType
  sourceUrl
  region
  category
  contentAngle
  status
  publishedAt
  collectedAt
  createdAt
```

주요 값:

```
category
  ANIME
  CHARACTER
  FIGURE
  GOODS
  COLLECTION
  UNKNOWN

contentAngle
  NEWS
  COMPARE
  SIZE
  PRICE
  QUESTION
  GUIDE
  COLLECTION

status
  NEW
  KEEP
  HOLD
  IGNORE
```

## MVP에서 하지 않는 것

- X 자동 스크래핑
- 자동 게시
- LLM 자동 요약
- 벡터 DB
- 추천 모델
- 별도 백엔드 API
- 사용자 로그인
- 클라우드 스케줄러

먼저 실제로 며칠 사용하면서 어떤 소스와 필드가 필요한지 확인한 뒤 확장합니다.
