# 데이터 수집 대상

이 문서는 Subculture Researcher가 어떤 소스를 어떤 방식으로 다루는지 정리합니다. 실제 목록은 [sources.yaml](subculture/collection/sources.yaml)이 기준이며, 앱의 「수집 목록」 화면에서도 볼 수 있습니다.

## 자동 수집

`python collect.py`. GitHub Actions가 매일(KST 08:00, UTC 23:00)에 실행하며 로컬에서도 돌릴 수 있습니다. 수동 전용 소스(`manual_only`/`local_only`)는 건너뛰고, HTML 소스는 `robots.txt`를 확인합니다.

- 로컬 실행은 수집 후 로컬 DB 동기화와 AI 초안 생성까지 기본으로 하며(`--no-sync`, `--no-ai-draft`로 끔), `CI` 환경(Actions)에서는 둘 다 건너뜁니다.

### 상품·예약 정보 (피규어·굿즈)

| 소스 | 방식 | 저장 필드 |
|---|---|---|
| 피규어팜 예약상품 | 목록 → 상세 페이지 | 가격, 예약마감일, 입고예정, 제조사, 사진 |
| 피규어프레소 예약상품 | 목록 → 상세 페이지 | 가격, 예약 상태, 사진 |
| 따빼몰 호요버스·명조 굿즈 | 목록 → 상세 페이지 | 가격, 예약 상태·마감일, 사진 |
| 따빼몰 **신규입고**·**신규예약** | 전체 신규 목록(`cate_no=23`·`24`) → 상세 페이지 | 가격, 예약 상태·마감일, 사진 (작품 구분 없이 최신순 90건, GOODS) |
| **마니아하우스** 예약 상품·입고 완료 상품 | 목록(`cate_no=45`·`46`) → 상세 페이지 | 가격, 예약 상태, 사진 (최신순 각 70건, FIGURE) |
| **코믹스아트** 신작 상품·입고 완료 당일 발송 | 목록(`cate_no=1215`·`49`) 카드 | 가격(판매가), 예약 상태, 사진 (최신순 각 100건, FIGURE) |
| **헤로타임** 최신 예약 | 목록(`cate_no=51`) 카드 | 가격(판매가), 예약 상태, 사진 (최신순 40건, FIGURE) |
| **도키도키굿즈** 신상품 | 목록(`cate_no=28`) 카드 | 가격(판매가), 품절·예약 상태, 사진 (최신순 40건, GOODS) |
| **대원샵** 상품(`category/439827`) | 브라우저 렌더링(`render_js`) 목록 카드 | 가격, 예약·품절 뱃지, 사진 (첫 페이지 48건, GOODS) |
| **아트플렉스** 전체 상품(`category/50`) | 목록 카드(`?page=`) | 판매가, 입고·출하 예정(예약), 사진 (최신순 최대 100건, GOODS) |
| **이딴가게** 신규 입고(`category/25`) | 목록 카드(`?page=`) | 판매가, 품절 여부, 사진 (최신순 최대 48건, FIGURE) |
| **라프텔 스토어** 신상품 | 홈의 `NEW` 배지 상품 카드 | 상품명(IP명 포함), 가격, 예약/입고 상태, 사진 |
| **애니메이트 코리아 신상품** | 신상품 목록(`cateCd=008`) 카드 | 상품명, 가격, 품절 여부, 사진 (국내·일본 서적은 제외) |
| **애니메이트 코리아 예약상품** | 예약상품-굿즈 목록(`cateCd=010006`) 카드 | 상품명, 가격, 예약 상태, 사진 (최신 3페이지, GOODS·PRICE) |

- 라프텔 스토어와 애니메이트 코리아 신상품은 로그인이 필요 없는 공개 HTML이며 `robots.txt`가 허용합니다. **목록 카드 텍스트에서 값을 읽기 때문에 상세 페이지를 요청하지 않고**, 그래서 예약마감일은 수집하지 않습니다(라프텔은 상세 페이지에만 있음).
- 애니메이트 코리아에는 피규어 전용 카테고리가 없어 굿즈 중심입니다. 예약상품은 상위 목록(`cateCd=010`) 앞쪽이 대부분 서적이라 굿즈 하위 목록(`010006`)을 읽고, 예약 표시가 아이콘 `alt`(★수주예약상품★)에만 있어 `card_alt_text: true`로 읽습니다.
- 헤로타임(Cafe24)은 코믹스아트와 같은 카드 구조라 상세를 열지 않고 목록 카드만 읽습니다. 카드에 「예약」 단어 없이 `마감 :`·`발매 :` 라벨만 있어 그 라벨을 예약 신호로 넣었고, 마감에 연도가 없어 `preorderEndAt`은 비웁니다. 이름 앞의 숨김 `상품명 :` 라벨은 `title_strip_pattern`으로 걷어 냅니다.
- 도키도키굿즈(Cafe24)의 `robots.txt`는 `sort=`·`filter=` 쿼리를 막으므로 정렬 파라미터 없이 기본 목록(`?cate_no=28&page=N`)만 읽습니다. 품절은 카드에 텍스트 없이 `alt="품절"` 아이콘으로만 나와 `card_alt_text: true`로 alt를 읽고, 제목의 `[25년 12월 발매]` 꼬리표를 예약 신호로 봅니다(품절이 우선).
- 대원샵(NHN Commerce)은 목록을 JS로 그려 Chromium 렌더링이 필요합니다(`python -m playwright install chromium`). 카드 텍스트는 `브랜드 제목 29,000 290 예약 신규 새창 찜 장바구니` 순서라 가격은 「새창」 앞 금액을 `price_pattern`으로 읽고(뒤의 숫자는 적립 포인트), 상태는 `예약`·`품절` 뱃지 텍스트로 정합니다. 페이지 이동이 링크 없는 버튼이라 첫 페이지(48건)만 봅니다. 카테고리 439827의 이름은 확인하지 못해 번호로 부릅니다.
- 아트플렉스(Cafe24)는 붕괴 스타레일 같은 게임·애니 정품 굿즈와 피규어가 섞인 전체 상품 목록입니다. `robots.txt`가 `?sort=`·`?filter=` 쿼리를 막으므로 받은 주소의 `?filter_view=1` 없이 기본 목록만 읽습니다. 카드에 「예약」 단어 없이 `26년 10월 입고 예정`·`27년 4월 출하 예정` 요약만 있어 `preorder_words`로 예약 신호로 삼고, 판매가 뒤에 나오는 `최적할인가`(쿠폰가)는 쓰지 않습니다. 상품 링크(`/product/{슬러그}/{번호}/category/50/display/1/`)는 `url_identity`가 `product_no` 주소로 통일합니다.
- 이딴가게(잇탄스토어, Cafe24)는 재고가 있는 신규 입고 상품이라 예약이 아닌 판매중으로 봅니다. 제목의 `[10월 8일 발송예정]`은 입고분의 발송 일정이라 예약 신호로 쓰지 않고 제목에 그대로 둡니다. 소비자가(취소선)가 먼저 나오는 카드가 있어 `price_pattern`으로 판매가만 읽고, 품절 아이콘은 `card_alt_text`로 읽습니다.
- 라프텔 홈의 `NEW` 배지는 그때그때 진행 중인 캠페인(예: 특정 IP)에 쏠릴 수 있습니다.
- 마니아하우스(Cafe24)는 피규어·프라모델이 섞인 키덜트샵이고 예약 상품 약 2.8천 건, 입고 완료 상품 약 1.7만 건이라 최신순 앞부분만 봅니다. 상세의 예약금·잔금 옵션 문구가 [입고완료] 상품을 예약으로 오인시키므로 기본 정보 블록(`.xans-product-detaildesign`)만 읽습니다. 상품 URL은 다른 Cafe24 샵처럼 `product_no`로 통일합니다.
- 코믹스아트(Cafe24)는 상세 본문에 모든 상품 공통의 「예약주문」 버튼 문구가 있어 상태가 오염되므로 상세를 열지 않고 **목록 카드 텍스트**만 읽습니다. 카드에 「예약」 단어 없이 `발매 :`·`마감 :`만 있어 신작 소스는 이를 `preorder_words`로 예약 신호로 삼고, 할인 카드는 소비자가가 먼저 나와 `price_pattern`으로 「판매가」 금액을 읽습니다. 마감일은 연도가 없어(`10월 26일`) `preorderEndAt`은 비어 있습니다. 링크가 `/category/N/display/N/`로 끝나는 SEO 경로라 `subculture/collection/domain/url_identity.py`가 그 꼬리를 떼고 `product_no`를 잡으며, 목록 끝의 `{$url}` 템플릿 카드는 `allow_patterns`로 걸러집니다.

### 뉴스·화제 (작품 발굴용)

| 소스 | 방식 |
|---|---|
| HOBBY Watch 피규어 | 목록 카드(기사 링크·사진) |
| Animate Times 굿즈 | 목록 카드 (`.c-item`) |
| McFarlane Toys 뉴스 | 목록 → 상세 `og:image` |
| AGF Korea 공지사항 | 공개 JSON API (공지 본문 이미지) |
| **애니플러스 뉴스** | 브라우저 렌더링(`render_js`) 목록 카드 (기사 링크·게시일·사진, 최신 3페이지, ANIME) |
| **ALTER 상품** | 공식 상품 목록(`/products/`, 발매월 최신순) 카드 (상품명·사진, 30건, FIGURE·공식) |
| **게임메카 모바일 게임 뉴스** | 목록(`news.php?ca=M`) 카드 (기사 링크·썸네일, 첫 페이지 20건, CHARACTER) |

- 애니플러스 뉴스는 목록을 JS로 그려 Chromium 렌더링이 필요합니다. `robots.txt`는 `/api/`만 막습니다. 예전처럼 좋아요 수는 읽지 않고 상세 페이지도 열지 않습니다.
- ALTER는 `robots.txt`가 없어(404) 허용으로 봅니다. 「花火」처럼 짧은 상품명이 있어 `min_title_length: 1`입니다. 목록이 발매월 순이라 새로 공개된 상품이 보통 맨 앞(가장 먼 발매월)에 옵니다.
- 게임메카는 `robots.txt`에 `Crawl-delay: 30`이 있어 요청 간격을 30–40초로 두고 첫 페이지만 읽습니다. 모바일 게임 전체 뉴스라 MMO 기사도 섞입니다.

### 저장 규칙 (공통)

- 제목·링크·출처·분류와 상품 메타데이터만 저장하며 원문 전체는 복제하지 않습니다.
- 동일 URL은 `ContentStore`가 SHA-256 기반 문서 ID로 중복을 막고, 재수집 시 값(가격·상태·사진)만 갱신합니다.
- Cafe24 등 등록된 샵은 SEO 경로와 짧은 주소를 `product_no` 쿼리 형태로 통일합니다(`subculture/collection/domain/url_identity.py`). 새 플랫폼은 규칙 타입을 추가합니다.

## 수동 수집

아래 소스는 GitHub Actions/`collect.py`에서 돌리지 않고 `python collect_manual.py`로만 실행합니다. `sources.yaml`에서 `manual_only: true`(또는 `local_only: true`)로 표시하며, `collect.py --source`에 수동 소스를, `collect_manual.py --source`에 자동 소스를 주면 오류가 납니다. AI 초안은 `--ai-draft`를 줄 때만 만듭니다(기본 꺼짐).
브라우저 기반 수동 소스(`type: local_browser`, `local_only: true`)는 창을 띄운 **시크릿(디스크 프로필 없음) Playwright 브라우저**에서 실행합니다. 캡차·인증은 소스별 `interactive_ready` 랜덤 대기 시간에 사용자가 직접 처리하며 우회는 시도하지 않습니다. 이 방식은 `robots.txt`를 확인하지 않으므로 사용자가 화면 앞에서 지켜보는 목록 수집에만 씁니다(저장된 프로필이 필요하면 소스에 `persistent_profile: true`).

소스 등록 없이 하는 수동 입력도 있습니다: 인박스 「+ 콘텐츠 추가」로 URL을 직접 저장하는 방식이며 네이버 스토어 수집의 보조 수단입니다(아래 코토부키야 몰·메가하우스 몰).

### 애니메이션 소스 (제거됨)

- AniList 트렌딩 애니, PR TIMES 만화·애니와 `anilist`·`youtube_feed` 수집기, AniList 지표(트렌딩·인기도·즐겨찾기·평균점수) 기반 점수·AI 프롬프트, 작품별 「애니」 초안을 제거했습니다. 이미 수집된 `ANIME` 문서는 지우지 않고 남깁니다.
- 애니플러스 뉴스는 지표 없이 기사 링크·사진만 다시 자동 수집합니다(위 「뉴스·화제」). 유일한 `ANIME` 소스입니다.
- 애니메이션 본편을 올리는 YouTube 채널(KADOKAWA Anime / Aniplex / TOHO animation 등)은 소스로 추가하지 않습니다.

라프텔은 **스토어**(`store.laftel.net`)만 자동 HTML로 수집합니다. `laftel.net` 인기·신작 브라우저 수집은 쓰지 않습니다.

### 네이버 스토어 (브라우저 수동 수집)

`python collect_manual.py --source "소스이름"`으로 실행합니다. 창이 열리면 캡차·인증을 직접 처리하고 상품 목록이 보이는 상태로 두세요. 대기 후 현재 화면의 상품 링크·카드 텍스트(가격·상태)·대표 이미지만 읽습니다. `collect.py`(GitHub Actions)는 이 소스를 건너뜁니다.

| 소스 | 목록 URL | 저장 |
|---|---|---|
| 코토부키야 몰 | https://brand.naver.com/kotobukiyamall (카테고리 URL이 정해지면 교체) | `shop=코토부키야 몰(네이버)` |
| 메가하우스 몰 입고 상품 | [입고 상품](https://smartstore.naver.com/megahousemall/category/5ba2f27d4bde41c4ba84f1fd9c83364a?cp=1) | `shop=메가하우스 몰(네이버)`, NEWS |
| 메가하우스 몰 예약 상품 | [예약 상품](https://smartstore.naver.com/megahousemall/category/a5876c8b741541e7ad056af202efdfb6?cp=1) | `shop=메가하우스 몰(네이버)`, PRICE |

- `brand.naver.com`·`smartstore.naver.com`의 `robots.txt`는 모든 봇에 `Disallow: /`이고 일반 요청에는 HTTP 429를 반환하므로 **자동 수집 대상이 아닙니다.** 위 소스는 사용자가 입회하는 로컬 시크릿 브라우저 수동 수집이라는 예외로만 둡니다(목록 페이지만, 느린 속도, 챌린지 우회 없음).
- 셀렉터(`a[href*="/products/"]`)는 실제 화면에서 확인하지 못한 값입니다. 처음에는 `--dry-run`으로 결과를 확인하세요.
- 수집이 막히면 인박스의 「+ 콘텐츠 추가」에서 상품 URL을 직접 저장할 수 있습니다. 카테고리를 「피규어」로 고르면 같은 `shop` 값의 상품(`entityType=PRODUCT`)으로 저장되고, 「이미지 URL」에 상품 사진 주소를 붙여 넣을 수 있습니다.

## 제외한 소스

Good Smile 뉴스(배송·점검 공지뿐), 애니메이트 코리아 페어·이벤트, 일러스타 페스, 코믹월드, Kotobukiya 뉴스(로컬 브라우저), animate 서울홍대점(X), 라프텔 인기·신작(브라우저)은 신상품·예약 정보를 얻지 못하거나 스토어 HTML로 대체되어 제거했습니다.
Wonder Festival·Comiket·Anime Festival Asia는 구조상 자동 수집이 어려워 붙이지 않았습니다(사유는 `sources.yaml` 하단 주석).
굿스마일컴퍼니 상품 목록은 예약·신상품 목록이 모두 `/{언어}/search` 경로라 `robots.txt`(`Disallow: /*/search`)에 막히고, FREEing·1999.co.jp는 `Disallow: /`, 코믹나탈리는 `robots.txt` 요청이 403이라 붙이지 않았습니다.

## 이미지 수집

글·상품 정보에 실제로 쓰인 사진의 **링크(URL)만** 저장합니다(Firestore에는 이미지 파일을 올리지 않고, 화면에서 원본 주소를 그대로 불러옵니다). 대표 사진은 `imageUrl`, 상품 상세 본문·갤러리 사진은 `detailImageUrls`(배열)입니다. 로고·아이콘·플레이스홀더·사이트 공통 공유 이미지는 `subculture/shared/image_urls.py` 규칙으로 걸러내며, 저장 전 `ContentStore.save`가 http(s) 링크인지 다시 확인합니다.

항목의 대표·상세 이미지를 **로컬로 받는** 기능은 Firestore와 별개입니다. 작품·기획의 「이미지 내보내기…」 팝업(현재 조건 전체 또는 선택 항목, 개수 제한 없음, 백그라운드 진행) 또는 `python export_images.py`가 `~/figure_project/exports/<stamp>/`(`.env`의 `FIGURE_PROJECT_DIR`로 변경)에 파일과 `index.json`을 만듭니다. 팝업에서 받을 항목 수·항목당 이미지 수·요청 간격·대표/상세 포함·총용량 상한을 정하고, 이미 받은 이미지 URL은 `exports/ledger.jsonl` 기준으로 건너뜁니다. 웹은 ZIP을 만들지 않습니다. figure-cutout이 같은 경로에서 읽습니다. 형식은 [docs/image-export-format.md](docs/image-export-format.md).

## 소스 설정 키 (HTML 소스)

| 설정 키 | 의미 |
|---|---|
| `link_selector` | 기사·상품 링크 셀렉터. `:-soup-contains("NEW")`처럼 링크 텍스트 조건도 쓸 수 있음 |
| `allow_patterns` / `deny_patterns` | 링크 URL 허용·제외 정규식 |
| `title_selector` | 링크 안에서 제목이 있는 요소 |
| `title_strip_pattern` | 제목 뒤에 붙은 가격·배지 텍스트를 지우는 정규식 |
| `title_deny_patterns` | 제목이 이 정규식과 맞으면 항목 제외(예: 서적) |
| `product_mode: true` | 상세 페이지를 열어 가격·예약 상태·마감일 추출 (한국 쇼핑몰용) |
| `list_product_mode: true` | **목록 카드 텍스트**에서 가격·예약 상태 추출. 상세는 `detail_images_selector`가 있을 때만 상세이미지를 위해 새 상품당 한 번 열고, 카드 값은 바꾸지 않음 |
| `price_pattern` | 가격 추출용 정규식(그룹 1 = 금액). 없으면 텍스트의 첫 1,000원 이상 금액. 소비자가·판매가가 함께 있는 카드용(예: `판매가\s*:\s*([\d,]+)\s*원`) |
| `card_alt_text` | `true`면 목록 카드 안 이미지의 `alt` 텍스트도 상태 판단(품절·예약)에 씀. 품절을 아이콘 `alt`로만 표시하는 몰용(기본 꺼짐) |
| `preorder_words` | 예약 상태로 볼 문구 목록. 기본 문구(`예약`, `PRE-ORDER` 등)에 더해지고 품절 문구가 있으면 품절이 우선 |
| `list_image_selector` | 목록 카드 안의 이미지 셀렉터. 카드는 "다른 상품 링크가 나오기 직전까지의 상위 요소"로 자동 판별 |
| `fetch_detail_image: true` | 상세 페이지를 열어 `og:image`(→ `twitter:image`) 사용. 목록에 이미지가 없을 때만 |
| `image_selector` | 상세 페이지에서 `og:image` 대신 쓸 이미지 셀렉터 |
| `detail_images_selector` | 상세 본문·갤러리의 **여러** `<img>`를 모아 `detailImageUrls`에 저장. `product_mode`·`list_product_mode`(정적 HTML)에서 쓰며, 없으면 갤러리를 긁지 않음. Cafe24 본문의 `ec-data-src`도 읽고 `{$...}` 템플릿 자리표시는 버림 |
| `image_deny_patterns` | 소스별로 추가 배제할 이미지 경로 정규식(예: 저화질 미리보기 `blur_\d+`) |
| `image_field` / `image_html_field` | JSON API 소스: 이미지 URL 필드 / 본문 HTML 필드(첫 `<img>` 사용) |
| `page_param` / `max_pages` | 목록 페이지네이션(HTML·JSON API). 1페이지는 `url` 그대로, 2페이지부터 쿼리 `page_param=N`. 새 링크가 없는 페이지·`max_items`·`max_pages`에서 멈추고, 2페이지 이후 robots.txt 거부는 앞 페이지 결과만 남기고 중단 |
| `page_count_field` | JSON API: 응답의 전체 페이지 수 필드. 여기까지만 요청 |
| `detail_refresh_hours` | 이미 저장된 URL의 상세 재요청 간격(기본 72시간, `0`이면 항상 요청). 상품(`product_mode`)은 이 간격마다 가격·예약 상태를 갱신, 사진 전용(`fetch_detail_image`)은 사진이 있으면 다시 열지 않고 없으면 이 간격으로만 재시도. `detail_images_selector`가 있는데 `detailImageUrls`가 아직 없으면 간격과 무관하게 한 번 상세를 다시 연다 |

`type: local_browser`(브라우저 수동 수집) 전용 키: `local_only: true`(자동 수집 제외), `interactive_ready`·`interactive_message`·`ready_wait_min_seconds`/`ready_wait_max_seconds`(사용자가 화면을 준비하는 랜덤 대기), `scroll_steps`·`scroll_delay_seconds`, `persistent_profile: true`(기본은 시크릿 컨텍스트). 이 방식의 `product_mode`는 상세를 열지 않고 목록 카드 텍스트에서 가격·상태를 읽습니다(상세 갤러리 URL은 수집하지 않음).

이미 저장된 항목은 다음 수집 때 같은 URL의 값(사진 포함)이 갱신됩니다(로컬 라이브러리에는 다시 동기화해야 반영).

### 소스별 목록 규모 메모

- 페이지네이션 사용: 아트플렉스(`?page=`, 60건/페이지, 최신 2페이지)·이딴가게(`?page=`, 24건/페이지, 최신 2페이지), 헤로타임(`?page=`, 20건/페이지)·도키도키굿즈(`?page=`, 20건/페이지, 최신 2페이지), 따빼몰(호요버스·명조·신규입고·신규예약, `?page=`, 30건/페이지), 마니아하우스(예약·입고완료, `&page=`, 35건/페이지), 코믹스아트(신작·입고 완료, `&page=`, 56건/페이지), 애니메이트 코리아 신상품·예약상품(`&page=`, 30건), Animate Times(`?p=`, 20건), AGF Korea(`gotoPage`, 10건, `pageCount`까지).
- 늘릴 수 없음: McFarlane Toys 뉴스는 사이트 자체가 게시물 2개, 라프텔 스토어는 홈 상품 46개 중 NEW 배지 상품만이 의도된 범위입니다.

## 캐시·보완·정리 명령

| 작업 | 명령 |
|---|---|
| 사진 없는 기존 문서 보완 | `python collect.py --backfill-images` |
| 제목 없음 잔여 문서 정리(X 게시물, `laftel.net` 홈) | `python delete_untitled_x.py --dry-run` 후 `--dry-run` 없이 실행 |
| 작품 링크 없는 항목 요약(카탈로그 보강용) | `python seed_works.py --unmatched` |
| 원격에서 사라진 로컬 항목 정리 | `python prune_library.py --dry-run` 후 `--dry-run` 없이 실행 |
| 수집 후 로컬 동기화 건너뛰기 | `python collect.py --no-sync` (`collect_manual.py`도 동일) |

- `--backfill-images`는 `imageUrl`이 비어 있는 문서에만 씁니다(덮어쓰지 않음). `fetch_detail_image` 소스의 상세 페이지를 최대 60건까지 robots.txt·요청 간격을 지키며 엽니다.
- `prune_library.py`는 Firestore에 없는 로컬 항목 중 작품 링크·기획 묶음·임시글 재료로 쓰이지 **않는 것만** 삭제합니다(동기화가 FIGURE에 자동으로 붙이는 「피규어」 카테고리는 작업으로 보지 않음)(있는 항목은 목록만 출력). 삭제 전 백업(PostgreSQL은 `.local/backups`의 pg_dump, SQLite는 `.bak` 복사)에 실패하면 아무것도 지우지 않습니다.
- 로컬에서 `collect.py`/`collect_manual.py`를 실행하면 시작 시 `[로컬 동기화] 마지막 … · 미동기화 N · 로컬에만 M`을 출력합니다. 수집기가 이미 읽은 문서 ID를 쓰므로 Firestore를 더 읽지 않고, 로컬 DB가 꺼져 있어도 수집은 계속됩니다. 자동 수집(GitHub Actions)은 `CI` 환경변수로 이 확인을 건너뜁니다.
- 임시글은 로컬 DB에만 있고 본문(`body`)과 댓글(`reply_body`, 상품 링크) 두 글로 저장됩니다. `reply_body` 컬럼이 추가되어(SQLite `0005_draft_reply_body`, PostgreSQL `pg0003_draft_reply_body`) 기존 임시글은 본문 그대로 두고 댓글을 빈 값으로 둡니다. 스키마가 바뀌었으므로 앱·동기화를 멈추고 `docker compose run --rm tools python migrate_library.py upgrade`로 업그레이드해야 글 화면이 열립니다(백업 자동). 발행하면 재료의 `postedAt`을 Firestore에도 기록합니다.
- Firestore 문서에 `detailCheckedAt`(상세 페이지를 마지막으로 확인한 시각) 필드가 추가됩니다. 스키마 마이그레이션과 새 Firestore 인덱스는 필요 없습니다.
- 조회수·좋아요(`viewCount`·`likeCount`)와 그 시간당 증가량(`*Velocity`)은 더 이상 수집·저장·점수 반영하지 않습니다(`list_metrics`·`detail_metrics` 설정 키도 제거). 추천 점수는 신선도와 공식·국내·예약·한정판 보너스로만 매깁니다. 기존 문서에 남은 필드는 무시됩니다.

## 수집 원칙

1. 자동 수집 전에 해당 사이트의 `robots.txt`를 확인합니다. 자동 수집을 금지하는 사이트(예: 네이버 브랜드스토어·스마트스토어)는 `collect.py` 소스로 등록하지 않습니다. 예외는 사용자가 입회해 로컬 시크릿 브라우저로 돌리는 `local_only` 수동 수집뿐입니다.
2. `robots.txt` 확인에 실패하면 자동 수집을 건너뜁니다.
3. 원문 전체를 복제하지 않고 제목, URL, 출처, 분류, 상품 메타데이터와 이미지 링크만 저장합니다.
4. X는 비공식 스크래핑하지 않습니다.
5. 동일 URL은 SHA-256 기반 Firestore document ID로 중복 저장을 방지합니다.
6. 사이트 구조가 바뀌어 수집 정확도가 떨어지면 해당 소스를 일시적으로 비활성화합니다.
7. HTTP 요청은 소스 간·상세 페이지 사이에 랜덤 대기를 두고, Accept 헤더는 브라우저와 비슷하게 보냅니다(User-Agent는 수집기 식별용을 유지하고 robots.txt를 지킵니다).

## 확장 후보

향후 필요성이 확인되면 아래를 추가할 수 있습니다.

- 공식 RSS 피드가 있는 소스
- 다른 제조사 신제품 페이지(robots.txt가 허용하는 곳)
- 라프텔 스토어 IP 페이지(`/ip/{id}`), 예약마감일 수집
- 키워드/IP/제조사 자동 분류
