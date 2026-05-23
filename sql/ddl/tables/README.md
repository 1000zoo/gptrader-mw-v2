# Table DDL

테이블별 `CREATE TABLE` DDL을 관리한다.

각 테이블 파일은 `reg_ymd`, `reg_dt`, `upd_dt`, `use_yn` 공통 컬럼을 포함해야 한다. `use_yn`은 `Y`, `N`만 허용하는 제약조건을 테이블 DDL 또는 `sql/ddl/constraints`에 반드시 가져야 한다.

