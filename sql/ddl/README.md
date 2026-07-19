# DDL

테이블, 인덱스, 제약조건 DDL을 관리한다.

DDL은 도메인별 디렉토리 아래에서 관리한다.

```text
sql/ddl/
  <domain>/
    tables/
    indexes/
    constraints/
```

테이블 DDL을 바꾸는 에이전트는 같은 도메인의 `tables`, `indexes`, `constraints`를 함께 확인해야 한다. 여러 도메인을 연결하는 FK나 조회 인덱스는 주 소유 도메인에 두고, 필요한 경우 파일 주석에 참조 도메인을 적는다.
