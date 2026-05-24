# SQL Persistence Review Issues

이 문서는 `docs/plan/sql` 기준으로 `sql` 하위 DDL과 검증 쿼리를 리뷰하며 발견한 문제를 누적 추적한다.

## 상태 규칙

- `open`: 아직 해결되지 않음
- `in progress`: 수정 작업 진행 중
- `resolved`: 수정 완료
- `won't fix`: 의도된 차이로 남김

## 이슈 목록

| Issue | Severity | Status | Detail |
|-------|----------|--------|--------|
| SQLite text primary keys allow NULL | `important` | `resolved` | [issues/sqlite-text-primary-keys-null.md](issues/sqlite-text-primary-keys-null.md) |
| Schema check omits generated indexes | `medium` | `resolved` | [issues/schema-check-missing-indexes.md](issues/schema-check-missing-indexes.md) |
| Schema check is too shallow | `medium` | `resolved` | [issues/schema-check-shallow-coverage.md](issues/schema-check-shallow-coverage.md) |
| Boolean spec to SQLite integer mapping is undocumented | `low` | `resolved` | [issues/boolean-sqlite-integer-mapping.md](issues/boolean-sqlite-integer-mapping.md) |
