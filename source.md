# 데이터 수집 대상

이 문서는 Subculture Researcher에서 어떤 소스를 어떤 방식으로 다루는지 정리합니다.

## 자동 수집

### 피규어팜 예약상품

- URL: https://m.figurefarm.net/shop/big_section.php?cno1=1554
- 지역: 한국
- 티어: `MEDIA`
- 목적: 피규어 예약상품, 가격, 예약마감일, 입고예정, 제조사 수집
- 방식: 공개 목록 → 상세 페이지 메타데이터 수집
- 기본 카테고리: `FIGURE`
- 기본 포맷: `PRICE`
- 저장 필드: `entityType=PRODUCT`, `shop=FigureFarm`, `saleStatus`, `price`, `preorderEndAt`, `releaseWindowText`, `manufacturer`

### HOBBY Watch 피규어

- URL: https://hobby.watch.impress.co.jp/category/figure/
- 지역: 일본
- 티어: `MEDIA`
- 목적: 피규어 신제품, 예약, 발매, 리뷰 후보 수집
- 방식: HTML 목록 링크 수집
- 기본 카테고리: `FIGURE`
- 기본 포맷: `NEWS`

### Good Smile Company 뉴스

- URL: https://www.goodsmile.com/en/news
- 지역: 일본
- 티어: `OFFICIAL`
- 목적: 제조사 공식 신제품/예약/발매 공지 수집
- 방식: HTML 목록 링크 수집
- 기본 카테고리: `FIGURE`
- 기본 포맷: `NEWS`

### Animate Times 굿즈

- URL: https://www.animatetimes.com/goods/
- 지역: 일본
- 티어: `MEDIA`
- 목적: 굿즈·피규어·페어 등 일본 미디어 허브 후보 수집
- 방식: HTML 목록 링크 수집 (`.c-item` 본문 카드만)
- 기본 카테고리: `GOODS`
- 기본 포맷: `NEWS`

### 애니플러스 뉴스

- URL: https://news.aniplustv.com/
- 지역: 한국
- 티어: `MEDIA`
- 목적: 국내 애니메이션/서브컬처 화제 후보 수집
- 방식: HTML 목록 링크 수집
- 기본 카테고리: `ANIME`
- 기본 포맷: `NEWS`

## 설정만 두고 비활성

### Kotobukiya 뉴스

- URL: https://www.kotobukiya.co.jp/en/news/
- 지역: 일본
- 티어: `OFFICIAL`
- 목적: 제조사 공식 공지
- 상태: Cloudflare가 단순 HTTP를 막아 `enabled: false`
- 재활성 조건: 브라우저 렌더링 수집이 안정적으로 통과할 때

### 애니메이트 코리아 페어·이벤트

- URL: https://www.animate-onlineshop.co.kr/board/list.php?bdId=event
- 지역: 한국
- 티어: `MEDIA`
- 목적: 국내 페어·이벤트·입고성 소식
- 상태: 목록이 `javascript:gd_btn_view(...)` 이라 HTML 링크 수집 불가 → `enabled: false`
- 대안: 필요한 게시물 URL을 리뷰 앱에서 수동 추가로 저장

## 로컬 브라우저 수집

아래 소스는 GitHub Actions에서 자동 실행하지 않고, `python collect.py --local-browser`로만 실행합니다.
Playwright의 소스별 영속 프로필을 사용하므로 로그인 쿠키/세션을 로컬에 유지할 수 있습니다.
로그인, MFA, Cloudflare 확인은 사용자가 열린 브라우저에서 직접 완료합니다.

### 라프텔 인기·신작

- URL: https://laftel.net/
- 카테고리: `ANIME`
- 프로필: `laftel`
- 방식: 로그인 후 인기 애니/이번주/분기/요일별 신작 화면으로 직접 이동 → Enter → 현재 화면 링크 수집

### 라프텔 스토어

- URL: https://laftel.net/
- 카테고리: `FIGURE`
- 프로필: `laftel` (애니 탐색과 세션 공유)
- 방식: 스토어 피규어/예약상품 화면으로 직접 이동 → Enter → 상품 링크와 주변 텍스트 수집
- 상품 필드: `entityType=PRODUCT`, `shop=Laftel`, `saleStatus`, `price`, `preorderEndAt`, `imageUrl`
- 예약일은 화면에 YYYY년 M월 D일 형식이 있을 때 추출

### animate 서울홍대점

- URL: https://x.com/animate_hongdae
- 카테고리: `GOODS`
- 프로필: `x-animate-hongdae`
- 방식: X 로그인/인증을 직접 완료한 뒤 공식 계정의 게시물 링크를 천천히 수집

### 애니메이트 코리아 페어·이벤트

- URL: https://www.animate-onlineshop.co.kr/board/list.php?bdId=event
- 카테고리: `FESTIVAL`
- 프로필: `animate-korea`
- 방식: JS 네비게이션 화면을 로컬 브라우저로 연 뒤 이벤트/페어 링크 수집

### 일러스타 페스

- URL: https://illustar.imweb.me/
- 카테고리: `FESTIVAL`
- 프로필: `illustar`
- 방식: 공지/티켓/행사 화면으로 이동 후 현재 페이지의 공식 링크 수집

### 코믹월드

- URL: https://comicw.co.kr/
- 카테고리: `FESTIVAL`
- 프로필: `comicworld`
- 방식: 공지/행사/티켓 화면으로 이동 후 현재 페이지 링크 수집

### Kotobukiya 뉴스

- URL: https://www.kotobukiya.co.jp/en/news/
- 카테고리: `FIGURE`
- 프로필: `kotobukiya`
- 방식: Cloudflare 확인이 필요한 경우 사용자가 직접 완료한 후 공식 뉴스/상품 링크 수집

AGF Korea는 현재 공개 JSON API가 있어 `FESTIVAL` 자동 수집을 유지하며, 로컬 브라우저 대상으로 중복 등록하지 않습니다.

## 수집 원칙

1. 자동 수집 전에 해당 사이트의 `robots.txt`를 확인합니다.
2. `robots.txt` 확인에 실패하면 자동 수집을 건너뜁니다.
3. 원문 전체를 복제하지 않고 제목, URL, 출처, 분류에 필요한 최소 메타데이터만 저장합니다.
4. X는 MVP에서 비공식 스크래핑하지 않습니다.
5. 동일 URL은 SHA-256 기반 Firestore document ID로 중복 저장을 방지합니다.
6. 사이트 구조가 바뀌어 수집 정확도가 떨어지면 해당 소스를 일시적으로 비활성화합니다.

## 확장 후보

향후 필요성이 확인되면 아래를 추가할 수 있습니다.

- 공식 RSS 피드가 있는 소스
- YouTube Data API 기반 피규어/애니 콘텐츠 수집
- 제조사별 신제품 페이지 (FREEing, Alter 등)
- Kotobukiya / 애니메이트 코리아 자동 수집 재활성
- 쇼핑몰 예약 시작/마감 정보
- 수집된 기사와 X 게시 성과 연결
- 키워드/IP/제조사 자동 분류
