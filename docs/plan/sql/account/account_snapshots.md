# account_snapshots

- Status: `ready`
- Domain: account
- Source: `src/domain/ports/account_port.py`, `src/domain/risk/exposure_limit.py`

## 목적

거래 실행 또는 리스크 계산 시점의 계좌 총 equity와 잔고 묶음을 저장한다.

## 저장 단위

한 row는 하나의 `AccountSnapshot` 헤더다. 개별 잔고는 `asset_balances`에 저장한다.

## 컬럼

| Column | Type | Required | Definition |
|--------|------|----------|------------|
| account_snapshot_id | text | yes | 계좌 snapshot 식별자. |
| exchange | text | no | 거래소. 예: `binance`. |
| account_id | text | no | 외부 계좌 식별자 또는 별칭. |
| total_equity | numeric | yes | 총 equity. 0 이상. |
| balance_count | integer | yes | 포함 잔고 수. 0 이상. |
| captured_dt | timestamptz | yes | snapshot 수집 시각. |
| payload | json | no | 거래소 원본 계좌 payload. |
| reg_ymd | text | yes | 등록일 `YYYYMMDD`. |
| reg_dt | timestamptz | yes | 등록 시각. |
| upd_dt | timestamptz | yes | 수정 시각. |
| use_yn | text | yes | 사용 여부. `Y` 또는 `N`. |

## 키와 인덱스

- PK: `account_snapshot_id`
- Index: `(exchange, account_id, reg_ymd, captured_dt)`
- Check: `total_equity >= 0`, `balance_count >= 0`, `use_yn IN ('Y', 'N')`
