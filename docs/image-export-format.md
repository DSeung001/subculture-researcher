# 이미지 내보내기 파일 양식 명세 (formatVersion 2)

작품·기획 「이미지 다운로드」와 `export_images.py`가 만드는 결과물의 파일 구조와 `export.json`, `index.json` 형식입니다.

## 1. 디렉터리 구조

```
<root>/
├── export.json
├── index.json
└── items/
    ├── FIGURE_3f2a…c9/
    │   ├── 00_main.jpg
    │   └── 02_detail.png
    └── GOODS_7b10…e4/
        └── 00_detail.webp
<root>.zip            # ZIP으로 받은 경우
```

| 요소 | 규칙 |
|---|---|
| `<root>` | 기본값 `.local/image_exports/<stamp>/`. `<stamp>`는 UTC `%Y%m%dT%H%M%S%fZ` (예: `20260923T041502123456Z`) |
| `items/<folder>/` | 항목마다 하나. `<folder>`는 항목 id에서 `[A-Za-z0-9._-]` 밖의 문자(`:` 포함)를 `_`로 바꾼 값(비면 `item`). 한 export 안에서 겹치면 `-2`, `-3`… 접미사. 이미지가 없는 항목도 빈 폴더가 생깁니다. `not_in_library` 항목은 폴더가 없습니다 |
| 파일 이름 | `<NN>_<role><ext>` |
| `<NN>` | 항목 안에서 0부터 매기는 순번, 최소 두 자리(`00`, `01`, …, 100번째부터 `100`). 대표 이미지가 있으면 `00`이고 상세 이미지가 그 뒤를 잇습니다. 받기에 실패한 이미지도 번호를 차지하므로 **디스크 번호에 빈칸이 생길 수 있습니다** |
| `<role>` | `main`(대표, `imageUrl`) 또는 `detail`(상세, `detailImageUrls`) |
| `<ext>` | 응답 본문의 매직 바이트로 판별한 포맷: `.jpg` `.png` `.gif` `.webp` `.bmp`. `Content-Type`과 URL은 쓰지 않습니다 |

### ZIP

- `<root>` 안의 모든 파일을 경로순으로 담고, 항목 이름은 `<root>` 기준 상대 경로(`/` 구분)입니다. 예: `export.json`, `index.json`, `items/FIGURE_3f2a…c9/00_main.jpg`
- 압축 방식은 `ZIP_DEFLATED`입니다. 빈 폴더는 ZIP에 들어가지 않습니다.
- 웹에서 받은 파일 이름은 `library-images-<stamp>.zip`입니다.

## 2. `export.json`

```json
{"formatVersion": 2, "createdAt": "2026-09-23T04:15:02.123456+00:00", "itemCount": 2, "fileCount": 3, "okCount": 2}
```

| 필드 | 타입 | 의미 |
|---|---|---|
| `formatVersion` | int | 양식 버전. 이 문서는 `2`. 파일이 없으면 v1(구 형식) |
| `createdAt` | string | UTC ISO 8601 |
| `itemCount` | int | `index.json` 원소 수 |
| `fileCount` | int | 모든 `files[]` 원소 수 |
| `okCount` | int | 그중 `status: "ok"` 수 |

`index.json` 직전에 씁니다.

## 3. `index.json`

- UTF-8(BOM 없음), 들여쓰기 2칸, 한글을 이스케이프하지 않습니다.
- 최상위는 **배열**이고, 원소 하나가 항목 하나입니다. 순서는 내보내기를 요청한 항목 순서입니다.
- 모든 다운로드가 끝난 뒤 마지막에 씁니다. `index.json`이 없는 폴더는 완료되지 않은 결과입니다.

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
  "detailImageUrls": ["https://cdn.example.com/d1.jpg", "https://cdn.example.com/d2.png"],
  "files": [
    {"key": "FIGURE_3f2a…c9-00", "role": "main", "url": "https://cdn.example.com/main.jpg", "path": "items/FIGURE_3f2a…c9/00_main.jpg", "status": "ok", "error": null, "format": "jpeg", "sha256": "9f86…08", "bytes": 48213},
    {"key": "FIGURE_3f2a…c9-01", "role": "detail", "url": "https://cdn.example.com/d1.jpg", "path": null, "status": "error", "error": "404 Client Error: Not Found for url: …", "format": null, "sha256": null, "bytes": null},
    {"key": "FIGURE_3f2a…c9-02", "role": "detail", "url": "https://cdn.example.com/d2.png", "path": "items/FIGURE_3f2a…c9/02_detail.png", "status": "ok", "error": null, "format": "png", "sha256": "6030…b3", "bytes": 102400}
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
| `files` | object[] | 다운로드 시도 결과. 대표(있으면) 먼저, 이어서 `detailImageUrls` 순서. 이미지가 없으면 `[]` |

### 3.2 `files[]` 원소

| 필드 | 타입 | 의미 |
|---|---|---|
| `key` | string | `<folder>-<NN>`. export 안에서 고유하고 파일 이름으로 쓸 수 있음. 실패한 파일에도 있음 |
| `role` | `"main"` \| `"detail"` | 대표 / 상세 |
| `url` | string | 요청한 이미지 URL |
| `path` | string \| null | 성공 시 `<root>` 기준 상대 경로(`/` 구분), 실패 시 `null` |
| `status` | `"ok"` \| `"error"` | 이미지 저장 성공 여부. 매직 바이트가 지원 포맷일 때만 `ok` |
| `error` | string \| null | 실패 시 예외 메시지(형식 자유), 성공 시 `null`. 본문이 이미지가 아니면 `not_image: <Content-Type>` |
| `format` | `"jpeg"` \| `"png"` \| `"gif"` \| `"webp"` \| `"bmp"` \| null | 매직 바이트로 판별한 포맷, 실패 시 `null` |
| `sha256` | string \| null | 저장한 바이트의 SHA-256(소문자 hex), 실패 시 `null` |
| `bytes` | int \| null | 저장한 바이트 수, 실패 시 `null` |

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
                "status": {"enum": ["ok", "error"]},
                "error": {"type": ["string", "null"]},
                "format": {"enum": ["jpeg", "png", "gif", "webp", "bmp", null]},
                "sha256": {"type": ["string", "null"]},
                "bytes": {"type": ["integer", "null"]}
              }
            }
          }
        }
      }
    ]
  }
}
```

## 4. 결과를 읽을 때

- 파일은 폴더에서 번호로 짝을 맞추지 말고 `files[].path`로 찾습니다. 받기에 실패한 파일도 번호를 차지하므로 디스크 번호에 빈칸이 생깁니다.
- `status: "ok"`는 매직 바이트까지 확인한 것입니다. 디코딩 가능 여부(잘린 파일 등)는 확인하지 않았습니다.
- 같은 이미지 URL은 한 항목 안에서만 합쳐지므로, 여러 항목이 같은 이미지를 쓰면 파일이 항목마다 따로 있습니다. `sha256`으로 중복을 찾습니다.
- 분류 기준으로는 `id` 앞부분(저장 카테고리)과 `category`(사용자가 고친 현재 카테고리) 중 무엇을 쓸지 정해야 합니다. 둘이 다를 수 있습니다.
- `export.json`이 없으면 v1(폴더명에 `:`, `key`·`format`·`sha256` 없음, HTML이 `ok`로 저장될 수 있음)입니다.
