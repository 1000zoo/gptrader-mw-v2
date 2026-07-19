# asset_balances

- Status: `done`
- Domain: account
- Source: `src/domain/ports/account_port.py`

## 목적

계좌 snapshot의 자산별 free/locked 잔고를 저장한다.

## 저장 단위

한 row는 하나의 `AssetBalance`다.

## 컬럼

| Column | Type | Required | Definition |
|--------|------|----------|------------|
| balance_id | text | yes | 잔고 row 식별자. |
| account_snapshot_id | text | yes | `account_snapshots.account_snapshot_id`. |
| asset | text | yes | 대문자로 정규화된 자산 코드. 예: `USDT`. |
| free | numeric | yes | 사용 가능 잔고. 0 이상. |
| locked | numeric | yes | 잠김 잔고. 0 이상. |
| total | numeric | yes | `free + locked` 값. 조회 최적화용. |
| reg_ymd | text | yes | 등록일 `YYYYMMDD`. |
| reg_dt | timestamptz | yes | 등록 시각. |
| upd_dt | timestamptz | yes | 수정 시각. |
| use_yn | text | yes | 사용 여부. `Y` 또는 `N`. |

## 키와 인덱스

- PK: `balance_id`
- Unique: `(account_snapshot_id, asset)`
- FK 후보: `account_snapshot_id -> account_snapshots.account_snapshot_id`
- Index: `(asset, reg_ymd, reg_dt)`
- Check: `free >= 0`, `locked >= 0`, `total >= 0`, `use_yn IN ('Y', 'N')`
