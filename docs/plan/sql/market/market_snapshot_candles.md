# market_snapshot_candles

- Status: `ready`
- Domain: market
- Source: `src/domain/market/market_snapshot.py`

## 목적

`market_snapshots`와 실제 `candles`를 순서 보존 방식으로 연결한다. 같은 캔들이 여러 스냅샷에서 재사용될 수 있게 한다.

## 저장 단위

한 row는 하나의 스냅샷에 포함된 하나의 캔들 참조다.

## 컬럼

| Column | Type | Required | Definition |
|--------|------|----------|------------|
| snapshot_id | text | yes | `market_snapshots.snapshot_id`. |
| sequence_no | integer | yes | 스냅샷 내부 캔들 순서. 1부터 증가한다. |
| symbol | text | yes | 참조 캔들의 심볼. |
| timeframe | text | yes | 참조 캔들의 타임프레임. |
| opened_at | timestamptz | yes | 참조 캔들의 시작 시각. |
| closed_at | timestamptz | yes | 참조 캔들의 종료 시각. |
| reg_ymd | text | yes | 등록일 `YYYYMMDD`. |
| reg_dt | timestamptz | yes | 등록 시각. |
| upd_dt | timestamptz | yes | 수정 시각. |
| use_yn | text | yes | 사용 여부. `Y` 또는 `N`. |

## 키와 인덱스

- PK: `(snapshot_id, sequence_no)`
- FK 후보: `snapshot_id -> market_snapshots.snapshot_id`
- FK 후보: `(symbol, timeframe, opened_at) -> candles(symbol, timeframe, opened_at)`
- Unique: `(snapshot_id, symbol, timeframe, opened_at)`
- Check: `sequence_no > 0`, `use_yn IN ('Y', 'N')`
