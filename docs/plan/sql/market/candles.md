# candles

- Status: `done`
- Domain: market
- Source: `src/domain/market/candle.py`, `src/domain/ports/market_data_port.py`

## 목적

거래소에서 수집한 OHLCV 캔들을 심볼/타임프레임/시각 단위로 보관한다. 백테스트, 지표 계산, 전략 실행 컨텍스트의 원천 데이터다.

## 저장 단위

한 row는 하나의 `Candle`이다. `symbol + timeframe + opened_at` 조합은 유일해야 한다.

## 컬럼

| Column | Type | Required | Definition |
|--------|------|----------|------------|
| symbol | text | yes | 거래 심볼. `Symbol.pair` 값. 예: `BTCUSDT`. |
| timeframe | text | yes | 캔들 주기. `Timeframe.name` 또는 외부 표준 문자열. |
| opened_at | timestamptz | yes | 캔들 시작 시각. |
| closed_at | timestamptz | yes | 캔들 종료 시각. `opened_at`보다 커야 한다. |
| open_price | numeric | yes | 시작 가격. `low_price`와 `high_price` 사이여야 한다. |
| high_price | numeric | yes | 최고 가격. |
| low_price | numeric | yes | 최저 가격. `high_price`보다 작거나 같아야 한다. |
| close_price | numeric | yes | 종료 가격. `low_price`와 `high_price` 사이여야 한다. |
| volume | numeric | yes | 거래량. 0 이상이어야 한다. |
| source | text | no | 데이터 제공자. 예: `binance`. |
| payload | json | no | 거래소 원본 캔들 payload. |
| reg_ymd | text | yes | 등록일 `YYYYMMDD`. |
| reg_dt | timestamptz | yes | 등록 시각. |
| upd_dt | timestamptz | yes | 수정 시각. |
| use_yn | text | yes | 사용 여부. `Y` 또는 `N`. |

## 키와 인덱스

- PK 또는 UNIQUE: `(symbol, timeframe, opened_at)`
- Index: `(symbol, timeframe, reg_ymd, closed_at)`
- Check: `closed_at > opened_at`, `low_price <= high_price`, `volume >= 0`, `use_yn IN ('Y', 'N')`
