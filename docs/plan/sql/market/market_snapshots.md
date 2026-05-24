# market_snapshots

- Status: `ready`
- Domain: market
- Source: `src/domain/market/market_snapshot.py`, `src/domain/strategy/strategy_context.py`

## 목적

전략 실행 시점에 사용한 캔들 묶음의 경계를 저장한다. 재현 가능한 전략 판단, 드라이런, 백테스트 감사에 사용한다.

## 저장 단위

한 row는 하나의 `MarketSnapshot` 헤더다. 포함 캔들은 `market_snapshot_candles`에서 순서대로 연결한다.

## 컬럼

| Column | Type | Required | Definition |
|--------|------|----------|------------|
| snapshot_id | text | yes | 스냅샷 식별자. 애플리케이션이 생성한다. |
| symbol | text | yes | 스냅샷의 공통 심볼. |
| timeframe | text | yes | 스냅샷의 공통 타임프레임. |
| opened_at | timestamptz | yes | 첫 캔들의 시작 시각. |
| closed_at | timestamptz | yes | 마지막 캔들의 종료 시각. |
| candle_count | integer | yes | 연결된 캔들 수. 1 이상이어야 한다. |
| latest_candle_opened_at | timestamptz | yes | 최신 캔들의 시작 시각. |
| source | text | no | 스냅샷 생성 출처. 예: `trade`, `backtest`, `dry_run`. |
| metadata | json | no | 스냅샷 생성 조건, limit 등 부가 정보. |
| reg_ymd | text | yes | 등록일 `YYYYMMDD`. |
| reg_dt | timestamptz | yes | 등록 시각. |
| upd_dt | timestamptz | yes | 수정 시각. |
| use_yn | text | yes | 사용 여부. `Y` 또는 `N`. |

## 키와 인덱스

- PK: `snapshot_id`
- Index: `(symbol, timeframe, reg_ymd, closed_at)`
- Check: `candle_count > 0`, `closed_at > opened_at`, `use_yn IN ('Y', 'N')`
