# 데이터 수집 대상

이 문서는 Subculture Researcher에서 어떤 소스를 어떤 방식으로 다루는지 정리합니다.

## 자동 수집

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

## 수동 수집

아래 채널은 X 중심으로 운영되거나 자동 접근 정책을 별도로 확인해야 하므로 MVP에서는 자동 스크래핑하지 않습니다.
사용자 커뮤니티/포럼(예: DC 갤러리, 루리웹, 인벤 등) 글도 "신규 상품 · 애니메이션 정보 · 피규어 정보"만
남기는 정책에 따라 자동 수집 대상에 포함하지 않습니다.

### 라프텔

- 용도: 애니메이션 Top-of-Funnel 소재
- 관찰 포인트: 신작, 공개작, 캐릭터, 장면, 시즌 화제
- 저장 방법: 필요한 X 게시물 URL을 리뷰 앱에서 수동 저장

### animate 서울홍대점

- 용도: 굿즈/상품 반복 포맷 벤치마킹
- 관찰 포인트: 입고소식, 추천상품, 이벤트, 페어
- 저장 방법: 필요한 게시물 URL을 수동 저장

### AGF Korea

- 용도: 행사, 일정, 출연자, 티켓, 참가사 정보
- 관찰 포인트: FOMO, 일정형 콘텐츠, 정보 카드
- 저장 방법: 필요한 게시물 URL을 수동 저장

### 일러스타 페스

- 용도: 커뮤니티 톤과 UGC 방식 벤치마킹
- 관찰 포인트: 참가자 리포스트, 밈, 크리에이터 콘텐츠
- 저장 방법: 필요한 게시물 URL을 수동 저장

### 코믹월드

- 용도: CTA, 마감, 희소성 포맷 벤치마킹
- 관찰 포인트: 행사 공지, 이벤트, 참여 유도
- 저장 방법: 필요한 게시물 URL을 수동 저장

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
