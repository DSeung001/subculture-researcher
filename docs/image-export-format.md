# 이미지 내보내기 파일 양식 명세 (formatVersion 3)

작품·기획 「이미지 내보내기」와 `export_images.py`가 만드는 결과물의 파일 구조와 `export.json`, `index.json`, `ledger.jsonl` 형식입니다.

## 1. 디렉터리 구조

```
exports/
├── ledger.jsonl      # 받은 이미지 URL 장부 (모든 export가 공유)
├── <stamp>/          # = <root>
│   └── …
└── <stamp>.zip       # CLI --zip일 때만

<root>/
├── export.json
├── index.json
└── items/
    ├── FIGURE_3f2a…c9/
    │   ├── 00_main.jpg
    │   └── 02_detail.png
    └── GOODS_7b10…e4/
        └── 00_detail.webp
```

| 요소 | 규칙 |
|---|---|
| `<root>` | 기본값 `$FIGURE_PROJECT_DIR/exports/<stamp>/` (미설정 시 `~/figure_project/exports/<stamp>/`, 두 저장소의 `.env`로 변경). `<stamp>`는 UTC `%Y%m%dT%H%M%S%fZ` (예: `20260923T041502123456Z`) |
| `items/<folder>/` | 항목마다 하나. `<folder>`는 항목 id에서 `[A-Za-z0-9._-]` 밖의 문자(`:` 포함)를 `_`로 바꾼 값(비면 `item`). 한 export 안에서 겹치면 `-2`, `-3`… 접미사. 이미지가 없는 항목도 빈 폴더가 생깁니다. `not_in_library` 항목은 폴더가 없습니다 |
| 파일 이름 | `<NN>_<role><ext>` |
| `<NN>` | 항목 안에서 0부터 매기는 순번, 최소 두 자리(`00`, `01`, …, 100번째부터 `100`). 대표 이미지가 있으면 `00`이고 상세 이미지가 그 뒤를 잇습니다. 받기에 실패했거나 건너뛴(`skipped`) 이미지도 번호를 차지하므로 **디스크 번호에 빈칸이 생길 수 있습니다** |
| `<role>` | `main`(대표, `imageUrl`) 또는 `detail`(상세, `detailImageUrls`) |
| `<ext>` | 응답 본문의 매직 바이트로 판별한 포맷: `.jpg` `.png` `.gif` `.webp` `.bmp`. `Content-Type`과 URL은 쓰지 않습니다 |

### ZIP (CLI `--zip`만)

- 웹 내보내기는 ZIP을 만들지 않습니다. 결과는 `<root>` 폴더 그대로입니다.
- CLI `--zip`은 `<root>` 안의 모든 파일을 경로순으로 `<root>.zip`에 담습니다. 항목 이름은 `<root>` 기준 상대 경로(`/` 구분), 압축 방식은 `ZIP_DEFLATED`이고 빈 폴더는 들어가지 않습니다. 건너뛴 이미지는 이 export 폴더에 없으므로 ZIP에도 없습니다.

## 2. `export.json`

```json
{
  "formatVersion": 3,
  "createdAt": "2026-09-23T04:15:02.123456+00:00",
  "itemCount": 2,
  "fileCount": 4,
  "okCount": 2,
  "skippedCount": 1,
  "errorCount": 1,
  "bytes": 150613,
  "stopReason": null,
  "options": {
    "max_items": null, "max_images_per_item": null, "include_main": true, "include_detail": true,
    "pause_seconds": 0.35, "max_total_bytes": null, "skip_downloaded": true, "timeout": 30
  }
}
```

| 필드 | 타입 | 의미 |
|---|---|---|
| `formatVersion` | int | 양식 버전. 이 문서는 `3`. 파일이 없으면 v1(구 형식) |
| `createdAt` | string | UTC ISO 8601 |
| `itemCount` | int | `index.json` 원소 수 |
| `fileCount` | int | 모든 `files[]` 원소 수 |
| `okCount` | int | 그중 `status: "ok"` 수 (이번에 새로 받은 파일) |
| `skippedCount` | int | 그중 `status: "skipped"` 수 (이전 export에 이미 있는 파일) |
| `errorCount` | int | 그중 `status: "error"` 수 |
| `bytes` | int | 이번에 새로 저장한 바이트 합 (`skipped`는 포함 안 함) |
| `stopReason` | `null` \| `"size_limit"` \| `"cancelled"` | `null`이면 끝까지 처리. 아니면 도중에 멈춘 이유이고 `index.json`에는 멈춘 항목까지만 있음 |
| `options` | object | 이 export에 쓴 설정. `max_*`가 `null`이면 제한 없음, `max_total_bytes`는 바이트 단위 |

`index.json` 직전에 씁니다.

## 3. `index.json`

- UTF-8(BOM 없음), 들여쓰기 2칸, 한글을 이스케이프하지 않습니다.
- 최상위는 **배열**이고, 원소 하나가 항목 하나입니다. 순서는 내보내기를 요청한 항목 순서입니다(웹 「현재 조건 전체」는 화면 목록 순서). `options.max_items`가 있으면 앞에서부터 그 수만큼입니다.
- 다운로드가 끝나거나 멈춘 뒤 마지막에 씁니다. `index.json`이 없는 폴더는 비정상 종료된 결과입니다. 멈춘 경우는 `export.json`의 `stopReason`으로 구분합니다.

### 3.1 항목 (정상)

```json
{
  "id": "FIGURE:3f2a…c9",
  "title": "[예약] 넨도로이드 프리렌",
  "titleKo": "",
  "url": "https://shop.example.com/product/detail.html?product_no=123",
  "shop": "따빼몰",
  "category": "FIGURE",
  "source": "따빼몰 신규예약",
  "imageUrl": "https://cdn.example.com/main.jpg",
  "detailImageUrls": ["https://cdn.example.com/d1.jpg", "https://cdn.example.com/d2.png", "https://cdn.example.com/d3.jpg"],
  "files": [
    {"key": "FIGURE_3f2a…c9-00", "role": "main", "url": "https://cdn.example.com/main.jpg", "path": "items/FIGURE_3f2a…c9/00_main.jpg", "status": "ok", "error": null, "format": "jpeg", "sha256": "9f86…08", "bytes": 48213},
    {"key": "FIGURE_3f2a…c9-01", "role": "detail", "url": "https://cdn.example.com/d1.jpg", "path": null, "status": "error", "error": "404 Client Error: Not Found for url: …", "format": null, "sha256": null, "bytes": null},
    {"key": "FIGURE_3f2a…c9-02", "role": "detail", "url": "https://cdn.example.com/d2.png", "path": "items/FIGURE_3f2a…c9/02_detail.png", "status": "ok", "error": null, "format": "png", "sha256": "6030…b3", "bytes": 102400},
    {"key": "FIGURE_3f2a…c9-03", "role": "detail", "url": "https://cdn.example.com/d3.jpg", "path": null, "status": "skipped", "error": null, "format": "jpeg", "sha256": "1b4f…7a", "bytes": 38800, "previousPath": "20260922T010203000000Z/items/FIGURE_3f2a…c9/01_detail.jpg"}
  ]
}
```

| 필드 | 타입 | 의미 |
|---|---|---|
| `id` | string | 항목 id `STORAGE_CATEGORY:document_id`. 로컬 DB `items.id`와 같음 |
| `title` | string | 원문 제목, 없으면 `""` |
| `titleKo` | string | 한국어 번역 제목, 없으면 `""` |
| `url` | string | 원본 상품·기사 URL. http(s)가 아니면 저장된 값 그대로, 없으면 `""` |
| `shop` | string | 판매처, 없으면 `""` |
| `category` | string | 사용자가 바꿀 수 있는 현재 카테고리. **`id` 앞부분(저장 카테고리)과 다를 수 있음** |
| `source` | string | 수집 소스 이름(`sources.yaml`의 `name`), 없으면 `""` |
| `imageUrl` | string | 받으려 한 대표 이미지 URL. http(s)가 아니거나 없으면 `""` |
| `detailImageUrls` | string[] | 받으려 한 상세 이미지 URL. http(s)만 남기고, 대표 이미지와 겹치는 것과 중복을 뺀 뒤 원래 순서를 유지 |
| `files` | object[] | 다운로드 대상 결과. 대표(있으면) 먼저, 이어서 `detailImageUrls` 순서. `options`의 대표/상세 포함 여부와 `max_images_per_item`에 따라 앞 목록보다 적을 수 있음. 이미지가 없으면 `[]` |

### 3.2 `files[]` 원소

| 필드 | 타입 | 의미 |
|---|---|---|
| `key` | string | `<folder>-<NN>`. export 안에서 고유하고 파일 이름으로 쓸 수 있음. 실패한 파일에도 있음 |
| `role` | `"main"` \| `"detail"` | 대표 / 상세 |
| `url` | string | 요청한 이미지 URL |
| `path` | string \| null | `ok`일 때 `<root>` 기준 상대 경로(`/` 구분), 그 밖에는 `null` |
| `status` | `"ok"` \| `"skipped"` \| `"error"` | `ok`: 이번에 저장(매직 바이트가 지원 포맷일 때만). `skipped`: 이전 export에 같은 URL 파일이 있어 받지 않음. `error`: 실패 |
| `error` | string \| null | `error`일 때 사유(형식 자유), 그 밖에는 `null`. 본문이 이미지가 아니면 `not_image: <Content-Type>`, 총용량 상한을 넘겨 저장하지 않았으면 `size_limit` |
| `format` | `"jpeg"` \| `"png"` \| `"gif"` \| `"webp"` \| `"bmp"` \| null | 매직 바이트로 판별한 포맷(`skipped`는 장부 값), `error`면 `null` |
| `sha256` | string \| null | 파일의 SHA-256(소문자 hex, `skipped`는 장부 값), `error`면 `null` |
| `bytes` | int \| null | 파일 바이트 수(`skipped`는 장부 값), `error`면 `null` |
| `previousPath` | string | **`skipped`일 때만 있음.** 이전에 저장된 파일의 `exports` 폴더 기준 상대 경로(`<stamp>/items/…`) |

`files`의 위치 번호가 파일 이름의 `<NN>`과 같습니다(`files[i]` ↔ `<NN> = i`).

### 3.3 항목 (로컬 DB에 없음)

```json
{"id": "FIGURE:unknown", "error": "not_in_library", "files": []}
```

이 세 키만 있습니다. **정상 항목에는 `error` 키가 없으므로** `"error" in entry`로 구분합니다.

### 3.4 JSON Schema (`index.json`)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "array",
  "items": {
    "oneOf": [
      {
        "type": "object",
        "required": ["id", "error", "files"],
        "additionalProperties": false,
        "properties": {
          "id": {"type": "string"},
          "error": {"const": "not_in_library"},
          "files": {"type": "array", "maxItems": 0}
        }
      },
      {
        "type": "object",
        "required": ["id", "title", "titleKo", "url", "shop", "category", "source", "imageUrl", "detailImageUrls", "files"],
        "additionalProperties": false,
        "properties": {
          "id": {"type": "string"},
          "title": {"type": "string"},
          "titleKo": {"type": "string"},
          "url": {"type": "string"},
          "shop": {"type": "string"},
          "category": {"type": "string"},
          "source": {"type": "string"},
          "imageUrl": {"type": "string"},
          "detailImageUrls": {"type": "array", "items": {"type": "string"}},
          "files": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["key", "role", "url", "path", "status", "error", "format", "sha256", "bytes"],
              "additionalProperties": false,
              "properties": {
                "key": {"type": "string"},
                "role": {"enum": ["main", "detail"]},
                "url": {"type": "string"},
                "path": {"type": ["string", "null"]},
                "status": {"enum": ["ok", "skipped", "error"]},
                "error": {"type": ["string", "null"]},
                "format": {"enum": ["jpeg", "png", "gif", "webp", "bmp", null]},
                "sha256": {"type": ["string", "null"]},
                "bytes": {"type": ["integer", "null"]},
                "previousPath": {"type": "string"}
              }
            }
          }
        }
      }
    ]
  }
}
```

## 4. `ledger.jsonl` (받은 이미지 장부)

`exports/ledger.jsonl`. 한 줄에 JSON 객체 하나이고, 이미지를 저장할 때마다 한 줄씩 덧붙입니다. 같은 URL이 여러 줄이면 마지막 줄이 유효합니다.

```json
{"url": "https://cdn.example.com/d3.jpg", "path": "20260922T010203000000Z/items/FIGURE_3f2a…c9/01_detail.jpg", "sha256": "1b4f…7a", "bytes": 38800, "format": "jpeg", "downloadedAt": "2026-09-22T01:02:05.120000+00:00"}
```

| 필드 | 타입 | 의미 |
|---|---|---|
| `url` | string | 이미지 URL (스킵 판단 키) |
| `path` | string | `exports` 폴더 기준 상대 경로 |
| `sha256` / `bytes` / `format` | | 저장한 파일 정보 |
| `downloadedAt` | string \| null | UTC ISO 8601. 기존 export에서 채운 줄은 `null` |

- `skip_downloaded`가 켜져 있고, URL이 장부에 있으며, 그 `path` 파일이 아직 있으면 받지 않고 `skipped`로 기록합니다. 파일을 지웠으면 다시 받습니다.
- 장부가 없으면 처음 열 때 기존 `exports/*/index.json`의 `ok` 파일로 채웁니다.
- 한 export 안에서 여러 항목이 같은 이미지 URL을 쓰면 처음 한 번만 받고 나머지는 `skipped`입니다.

## 5. 결과를 읽을 때

- 파일은 폴더에서 번호로 짝을 맞추지 말고 `files[].path`로 찾습니다. 실패하거나 건너뛴 파일도 번호를 차지하므로 디스크 번호에 빈칸이 생깁니다.
- 새 이미지만 처리하려면 `status: "ok"`만 읽습니다. 항목의 모든 이미지가 필요하면 `skipped`의 `previousPath`(`exports` 기준)까지 함께 읽습니다.
- `status: "ok"`는 매직 바이트까지 확인한 것입니다. 디코딩 가능 여부(잘린 파일 등)는 확인하지 않았습니다.
- 같은 URL은 장부 덕분에 한 번만 저장됩니다. URL이 달라도 내용이 같은 이미지는 따로 저장되니 `sha256`으로 중복을 찾습니다.
- 분류 기준으로는 `id` 앞부분(저장 카테고리)과 `category`(사용자가 고친 현재 카테고리) 중 무엇을 쓸지 정해야 합니다. 둘이 다를 수 있습니다.
- `export.json`이 없으면 v1(폴더명에 `:`, `key`·`format`·`sha256` 없음, HTML이 `ok`로 저장될 수 있음), `formatVersion: 2`면 `skipped`·`stopReason`·장부가 없는 형식입니다.
