# 이미지 export 포맷 v4

소유: subculture-researcher. 두 저장소의 이 문서와 `tests/fixtures/image-export-v4.json`은 동일하게 유지한다.

## 저장 위치

두 프로그램에 같은 `FIGURE_PROJECT_DIR`을 설정한다. 기본값은 `~/figure_project`.

```text
<FIGURE_PROJECT_DIR>/
├── images/
│   ├── ledger.jsonl
│   └── <sha256 앞 2자리>/<sha256>.<ext>
└── exports/
    └── <UTC stamp>/
        ├── export.json
        └── index.json
```

- `--out`은 export 기록의 위치만 바꾼다. 원본 저장 위치는 설정으로 결정한다.
- 이미지 바이트의 SHA-256으로 중복을 제거한다. 확장자는 매직 바이트로 판별한다: jpeg→jpg, png, gif, webp, bmp.
- 임시 파일을 원자적으로 확정한 뒤 URL 장부를 갱신한다. 폴더는 파일 저장 시 생성한다.
- 원본 자동 삭제는 없다. export 삭제는 공용 원본에 영향을 주지 않는다.
- 이미지 없는 실행에도 결과 기록은 남긴다. `index.json`은 마지막에 쓰는 완료 표시다. `stopReason`으로 취소·용량 제한을 구분한다.

## export.json

| 필드 | 의미 |
|---|---|
| `formatVersion` | `4` |
| `createdAt` | UTC ISO 8601 |
| `itemCount`, `fileCount` | 기록한 항목 수, 파일 시도 수 |
| `okCount`, `skippedCount`, `errorCount` | 새 다운로드 성공, 네트워크 생략, 실패 수 |
| `bytes` | 이번 실행에서 다운로드·저장 성공한 응답 바이트 합. 동일 내용 재사용 시에도 집계하며 실제 추가 디스크 사용량과 다를 수 있음 |
| `stopReason` | `null`, `cancelled`, `size_limit` |
| `options` | 실행 옵션: max_items, max_images_per_item, include_main, include_detail, pause_seconds, max_total_bytes, skip_downloaded, timeout |

용량 제한은 `bytes`에 적용한다. 기존 원본 재사용·기존 export에서의 로컬 복사는 포함하지 않는다. `--no-skip`은 URL을 다시 다운로드하되 동일 내용의 원본은 추가하지 않는다.

## index.json

최상위는 요청 순서의 항목 배열이다. 정상 항목은 다음 필드를 가진다:

`id`, `title`, `titleKo`, `url`, `shop`, `category`, `source`, `imageUrl`, `detailImageUrls`, `files`.

- `id`는 저장 카테고리와 document ID의 조합이다. 수정 가능한 `category`와 다를 수 있다.
- 로컬 DB에 없는 항목: `{"id": "FIGURE:unknown", "error": "not_in_library", "files": []}`.
- `files`는 대표 이미지부터 상세 이미지 순서다. 이미지 없는 항목은 빈 배열이다.

| files 필드 | 계약 |
|---|---|
| `key` | 기존과 같은 `<안전한 item-id>-<NN>`. export 내 고유 sample ID. 실패·생략도 순번을 차지함 |
| `role` | `main` 또는 `detail` |
| `url` | 원본 이미지 URL |
| `status` | `ok`: 다운로드 성공, `skipped`: 네트워크 생략, `error`: 실패 |
| `storage` | 성공·생략 시 `shared` 또는 `export`; 실패 시 null |
| `path` | storage 기준 상대 경로(`/` 구분); 실패 시 null |
| `error` | 실패 메시지; 성공·생략 시 null |
| `format` | jpeg, png, gif, webp, bmp; 실패 시 null |
| `sha256`, `bytes` | 이미지 바이트의 해시와 크기; 실패 시 null |

`shared`는 `<FIGURE_PROJECT_DIR>/images/`, `export`는 `index.json`이 있는 폴더를 기준으로 한다. 절대 경로와 심볼릭 링크를 포함한 기준 폴더 이탈은 거부한다. v4의 `ok`와 `skipped` 모두 직접 해석 가능한 참조를 가진다.

```json
{"key":"FIGURE_example-00","role":"main","url":"https://cdn.example/main.png","status":"skipped","storage":"shared","path":"ab/<sha256>.png","error":null,"format":"png","sha256":"<sha256>","bytes":1234}
```

매직 바이트 통과는 완전한 이미지 디코딩을 보장하지 않는다. figure-cutout 초기화에서 디코딩·크기·분류 필터를 적용한다.

## 공용 장부

`images/ledger.jsonl`은 URL별 최신 원본 위치를 기록한다. 행 필드는 `url`, `path`(images 기준), `sha256`, `bytes`, `format`, `downloadedAt`이다. 경로의 실제 파일이 있어야 재사용한다.

- `formatVersion: 4`만 지원한다. 버전 누락·다른 버전은 거부한다.
- 기존 export 장부 조회, 원본 가져오기, 이전 실행 경로 참조는 지원하지 않는다.
- 기존 데이터를 사용하려면 새로 내보낸다. 기존 파일은 자동 수정·삭제하지 않는다.

## ZIP

CLI `--zip`으로 생성한다. v4 ZIP에는 `ok`·`skipped`가 참조하는 모든 이미지가 `images/<key>_<role>.<ext>`로 포함된다. ZIP 내부 index만 `storage: "export"`와 새 상대 경로로 변환한다. export 원본과 sidecar는 수정하지 않는다. 압축 해제한 ZIP은 공용 저장소 없이 읽을 수 있다.

파일 누락 등으로 ZIP 생성이 실패하면 임시 ZIP을 제거하고 기존 ZIP은 유지한다. ZIP 생성도 v4만 허용한다.
