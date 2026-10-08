# Repository guidance

이 저장소의 작업 규칙은 [AGENTS.md](AGENTS.md)를 따른다.

- 설정과 실행 명령: [README.md](README.md)
- 수집 대상과 정책: [source.md](source.md)
- 단위·시스템·E2E 범위와 불필요한 테스트 정리 기준: [테스트 가이드](docs/testing.md)

동작 변경에는 오프라인 회귀 테스트를 추가하고, 전달 전 `python -m unittest discover -s tests -v`를 실행한다. 실제 수집이나 운영 Firestore를 읽는 사이트 빌드를 테스트 대용으로 실행하지 않는다. 브라우저 테스트가 skip되면 미실행 사실과 이유를 보고한다.

허수·중복 테스트와 불필요한 소스 문자열 검사는 삭제하고, 관찰 가능한 동작을 검증한다. 구체적인 유지·삭제 기준은 테스트 가이드를 따른다.
