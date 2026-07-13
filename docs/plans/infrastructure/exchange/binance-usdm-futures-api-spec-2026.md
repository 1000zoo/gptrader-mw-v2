# Binance USD-M Futures API Specification (2026)

이 문서는 Binance USD-M Futures REST API 중 Gptrader V3 시스템에서 사용하는 핵심 엔드포인트를 요약한 개발 참고 스펙이다. 2026-05 기준 공식 문서 스펙에 맞춘 요약이며, 구현 시 Binance 공식 문서와 Change Log로 최종 확인한다.

참고: 모든 시간 `timestamp` 필드는 밀리초 단위이며, 대부분의 signed 요청에서 `timestamp`와 API 키 서명이 필요하다. 자세한 인증 절차는 Binance 공식 문서를 참조한다.

## 1. 캔들/시세 이력 조회

### 1.1 Kline Candlestick Data

- HTTP method: `GET`
- Endpoint: `/fapi/v1/klines`
- Purpose: 특정 심볼의 캔들스틱(OHLCV) 데이터를 조회한다. `startTime`과 `endTime`을 지정하지 않으면 최신 캔들부터 반환된다.

요청 파라미터:

| 이름 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `symbol` | `STRING` | 예 | 조회할 심볼. 예: `BTCUSDT` |
| `interval` | `ENUM` | 예 | 캔들 간격. 예: `1m`, `5m`, `1h`, `1d` |
| `startTime` | `LONG` | 아니오 | 조회 시작 시간, 밀리초 |
| `endTime` | `LONG` | 아니오 | 조회 종료 시간, 밀리초 |
| `limit` | `INT` | 아니오 | 반환할 캔들 수. 기본 500, 최대 1500 |

응답 예시:

```json
[
  1499040000000,
  "0.01634790",
  "0.80000000",
  "0.01575800",
  "0.01577100",
  "148976.11427815",
  1499644799999,
  "2434.19055334",
  308,
  "1756.87402397",
  "28.46694368",
  "17928899.62484339"
]
```

응답 배열 인덱스:

| 인덱스 | 필드 | 설명 |
| --- | --- | --- |
| 0 | open time | 캔들 시작 시간 |
| 1 | open | 시가 |
| 2 | high | 고가 |
| 3 | low | 저가 |
| 4 | close | 종가 |
| 5 | volume | 거래량 |
| 6 | close time | 캔들 종료 시간 |
| 7 | quote asset volume | 쿼트 자산 기준 거래량 |
| 8 | number of trades | 체결 건수 |
| 9 | taker buy base asset volume | 매수자 기준 베이스 자산량 |
| 10 | taker buy quote asset volume | 매수자 기준 쿼트 자산량 |
| 11 | ignore | 무시 가능한 값 |

거래량, 체결 건수 등은 전략 컨텍스트와 백테스트에서 사용할 수 있다.

### 1.2 현재 가격/호가 정보

#### 1.2.1 Symbol Price Ticker V2

- HTTP method: `GET`
- Endpoint: `/fapi/v2/ticker/price`
- Purpose: 심볼의 최신 거래 가격을 조회한다.

요청 파라미터:

| 이름 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `symbol` | `STRING` | 아니오 | 심볼을 지정하지 않으면 모든 심볼 가격을 배열로 반환 |

응답 예시:

```json
{
  "symbol": "BTCUSDT",
  "price": "6000.01",
  "time": 1589437530011
}
```

여러 심볼을 조회하면 배열 형식으로 반환될 수 있다.

#### 1.2.2 Symbol Order Book Ticker

- HTTP method: `GET`
- Endpoint: `/fapi/v1/ticker/bookTicker`
- Purpose: 특정 심볼 또는 전체 심볼의 최우선 매수/매도 호가와 수량을 조회한다.

요청 파라미터:

| 이름 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `symbol` | `STRING` | 아니오 | 심볼을 지정하지 않으면 모든 심볼에 대한 호가를 배열로 반환 |

응답 예시:

```json
{
  "symbol": "BTCUSDT",
  "bidPrice": "4.00000000",
  "bidQty": "431.00000000",
  "askPrice": "4.00000200",
  "askQty": "9.00000000",
  "time": 1589437530011
}
```

## 2. 계좌/잔고 조회

### 2.1 Futures Account Balance V2

- HTTP method: `GET`
- Endpoint: `/fapi/v2/balance`
- Purpose: 각 자산의 지갑 잔고, 사용 가능 잔고, 교차/격리 마진 정보를 조회한다.

요청 파라미터:

| 이름 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `timestamp` | `LONG` | 예 | 서명에 사용되는 요청 타임스탬프 |
| `recvWindow` | `LONG` | 아니오 | 요청 유효 시간. 기본값 5000ms |

응답 예시:

```json
[
  {
    "accountAlias": "SgsR",
    "asset": "USDT",
    "balance": "122607.35137903",
    "crossWalletBalance": "23.72469206",
    "crossUnPnl": "0.00000000",
    "availableBalance": "23.72469206",
    "maxWithdrawAmount": "23.72469206",
    "marginAvailable": true,
    "updateTime": 1617939110373
  }
]
```

주요 필드:

| 필드 | 설명 |
| --- | --- |
| `accountAlias` | 계정 식별 코드 |
| `asset` | 자산명 |
| `balance` | 지갑 총 잔고 |
| `crossWalletBalance` | 교차마진 지갑 잔고 |
| `crossUnPnl` | 교차포지션 미실현 손익 |
| `availableBalance` | 주문 가능 잔액 |
| `maxWithdrawAmount` | 출금 가능 최대 금액 |
| `marginAvailable` | Multi-Assets 모드에서 마진으로 사용 가능한지 여부 |
| `updateTime` | 마지막 업데이트 시간 |

### 2.2 Account Information V2

- HTTP method: `GET`
- Endpoint: `/fapi/v2/account`
- Purpose: 계정의 전체 지갑 잔고, 유지 증거금, 총 미실현 손익 등 계정 상태를 조회한다. 싱글 자산 모드와 멀티 자산 모드에서 일부 값이 달라질 수 있다.

요청 파라미터:

| 이름 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `timestamp` | `LONG` | 예 | 서명에 사용되는 요청 타임스탬프 |
| `recvWindow` | `LONG` | 아니오 | 요청 유효 시간 |

대표 필드:

| 필드 | 설명 |
| --- | --- |
| `feeTier` | 계정 수수료 티어 |
| `canTrade` / `canDeposit` / `canWithdraw` | 해당 작업 가능 여부 |
| `multiAssetsMargin` | 멀티 자산 모드 사용 여부 |
| `totalWalletBalance` | 계정 총 지갑 잔고, USDT 기준 |
| `totalUnrealizedProfit` | 계정 총 미실현 손익 |
| `totalMarginBalance` | 계정 총 마진 잔고. 지갑 잔고 + 미실현 손익 |
| `availableBalance` | 주문에 사용할 수 있는 자금 |
| `assets[]` | 각 자산의 상세 정보 객체 배열. `asset`, `walletBalance`, `unrealizedProfit`, `marginBalance`, `crossWalletBalance`, `availableBalance` 등을 포함 |

## 3. 주문 제출

### 3.1 New Order

- HTTP method: `POST`
- Endpoint: `/fapi/v1/order`
- Purpose: 새로운 주문을 제출한다.

주요 요청 파라미터:

| 이름 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `symbol` | `STRING` | 예 | 주문할 거래쌍. 예: `BTCUSDT` |
| `side` | `ENUM` | 예 | `BUY` 또는 `SELL` |
| `type` | `ENUM` | 예 | 주문 유형. `LIMIT`, `MARKET`, `STOP`, `TAKE_PROFIT` 등 |
| `timeInForce` | `ENUM` | 아니오 | 지정가 주문의 유효 시간. `GTC`, `IOC`, `FOK`, `GTD` |
| `quantity` | `DECIMAL` | 주문 유형에 따라 필수 | 주문 수량 |
| `price` | `DECIMAL` | 주문 유형에 따라 필수 | 지정가 주문 가격 |
| `reduceOnly` | `STRING` | 아니오 | `true`이면 포지션을 줄이는 용도로만 사용 |
| `newClientOrderId` | `STRING` | 아니오 | 고유 클라이언트 주문 ID, 36자 이내 |
| `newOrderRespType` | `ENUM` | 아니오 | `ACK` 또는 `RESULT`. 기본값 `ACK` |
| `timestamp` | `LONG` | 예 | 서명 및 타임스탬프 |

응답 예시:

```json
{
  "clientOrderId": "testOrder",
  "cumQty": "0",
  "cumQuote": "0",
  "executedQty": "0",
  "orderId": 22542179,
  "avgPrice": "0.00000",
  "origQty": "10",
  "price": "0",
  "reduceOnly": false,
  "side": "BUY",
  "positionSide": "SHORT",
  "status": "NEW",
  "stopPrice": "0",
  "closePosition": false,
  "symbol": "BTCUSDT",
  "timeInForce": "GTD",
  "type": "LIMIT",
  "origType": "LIMIT",
  "updateTime": 1566818724722,
  "workingType": "CONTRACT_PRICE",
  "priceProtect": false
}
```

주요 응답 필드:

| 필드 | 설명 |
| --- | --- |
| `clientOrderId` | 클라이언트 주문 ID |
| `cumQty` | 누적 체결 수량 |
| `cumQuote` | 누적 체결 금액 |
| `executedQty` | 실행된 수량 |
| `orderId` | 거래소 주문 ID |
| `avgPrice` | 평균 체결 가격 |
| `origQty` | 요청한 원래 수량 |
| `price` | 지정가 가격 |
| `reduceOnly` | 리듀스온리 여부 |
| `side` | 주문 방향 |
| `positionSide` | 포지션 모드 |
| `status` | 주문 상태. `NEW`, `PARTIALLY_FILLED`, `FILLED`, `CANCELED` 등 |
| `stopPrice` | 스탑 가격 |
| `closePosition` | 전체 포지션 종료 여부 |
| `timeInForce` | 주문 유효 시간 |
| `type` | 주문 유형 |
| `origType` | 원본 주문 유형 |
| `updateTime` | 업데이트 시간 |
| `workingType` | 트리거 기준 가격 종류 |
| `priceProtect` | 가격 보호 여부 |

### 3.2 Query Order / All Orders

#### 3.2.1 Query Order

- HTTP method: `GET`
- Endpoint: `/fapi/v1/order`
- Purpose: 특정 주문의 상태를 조회한다. `orderId` 또는 `origClientOrderId` 중 하나는 반드시 제공해야 한다.

주요 요청 파라미터:

| 이름 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `symbol` | `STRING` | 예 | 주문 심볼 |
| `orderId` | `LONG` | 아니오 | 거래소 주문 ID |
| `origClientOrderId` | `STRING` | 아니오 | 발주 시 사용한 client order ID |
| `timestamp` | `LONG` | 예 | 요청 시간 |
| `recvWindow` | `LONG` | 아니오 | 요청 유효 시간 |

응답은 주문 정보 객체를 반환하며 `avgPrice`, `cumQuote`, `executedQty`, `status`, `time`, `workingType` 등을 포함한다. 예를 들어 `status: "NEW"`는 주문이 아직 체결되지 않았음을 나타낸다.

#### 3.2.2 Query All Orders

- HTTP method: `GET`
- Endpoint: `/fapi/v1/allOrders`
- Purpose: 계정의 전체 주문 내역, 즉 활성/취소/체결 완료 주문을 조회한다. 최근 7일 내 주문만 반환하며, `orderId`를 지정하면 해당 ID 이상부터 조회한다.

주요 요청 파라미터:

| 이름 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `symbol` | `STRING` | 예 | 심볼 |
| `orderId` | `LONG` | 아니오 | 해당 주문 ID부터 조회 |
| `startTime` / `endTime` | `LONG` | 아니오 | 조회 기간. 최대 7일 |
| `limit` | `INT` | 아니오 | 기본 500, 최대 1000 |
| `timestamp` | `LONG` | 예 | 요청 시간 |

각 주문 객체는 `avgPrice`, `clientOrderId`, `executedQty`, `orderId`, `origQty`, `price`, `side`, `positionSide`, `status`, `stopPrice`, `activatePrice` 등을 포함한다. `priceMatch`, `selfTradePreventionMode`, `goodTillDate` 등의 부가 정보도 반환될 수 있다.

### 3.3 Trade History (User Trade List)

- HTTP method: `GET`
- Endpoint: `/fapi/v1/userTrades`
- Purpose: 특정 심볼의 체결 내역을 조회한다. 최근 6개월 이내 데이터만 제공되며, `startTime`과 `endTime`을 지정하지 않으면 최근 7일 데이터를 반환한다.

주요 요청 파라미터:

| 이름 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `symbol` | `STRING` | 예 | 심볼 |
| `fromId` | `LONG` | 아니오 | 해당 체결 ID부터 조회. `startTime`/`endTime`과 함께 사용할 수 없음 |
| `startTime` / `endTime` | `LONG` | 아니오 | 조회 기간. 최대 7일 |
| `limit` | `INT` | 아니오 | 기본 500, 최대 1000 |
| `timestamp` | `LONG` | 예 | 요청 시간 |

각 체결 객체 주요 필드:

| 필드 | 설명 |
| --- | --- |
| `buyer` | 본 계정이 매수자이면 `true` |
| `maker` | 메이커 여부 |
| `commission` | 수수료 |
| `commissionAsset` | 수수료 지불 자산 |
| `id` | 체결 ID |
| `orderId` | 주문 ID |
| `price` | 체결 가격 |
| `qty` | 체결 수량 |
| `quoteQty` | 체결 금액 |
| `realizedPnl` | 실현 손익 |
| `side` / `positionSide` | 매수/매도 방향 및 포지션 방향 |
| `time` | 체결 시간 |

## 4. 현재 포지션 조회

### 4.1 Position Information V2

- HTTP method: `GET`
- Endpoint: `/fapi/v2/positionRisk`
- Purpose: 현재 보유 포지션의 진입가격, 미실현 손익, 레버리지, 마진 타입 등을 조회한다. `symbol`을 지정하지 않으면 전체 포지션을 반환한다.

요청 파라미터:

| 이름 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `symbol` | `STRING` | 아니오 | 특정 심볼의 포지션만 조회 |
| `timestamp` | `LONG` | 예 | 요청 시간 |
| `recvWindow` | `LONG` | 아니오 | 요청 유효 시간 |

응답 예시, 헤지 모드:

```json
[
  {
    "symbol": "BTCUSDT",
    "positionAmt": "0.001",
    "entryPrice": "22185.2",
    "breakEvenPrice": "0.0",
    "markPrice": "21123.05052574",
    "unRealizedProfit": "-1.06214947",
    "liquidationPrice": "19731.45529116",
    "leverage": "4",
    "maxNotionalValue": "100000000",
    "marginType": "cross",
    "isolatedMargin": "0.00000000",
    "isAutoAddMargin": "false",
    "positionSide": "LONG",
    "notional": "21.12305052",
    "isolatedWallet": "0",
    "updateTime": 1655217461579
  }
]
```

주요 필드:

| 필드 | 설명 |
| --- | --- |
| `symbol` | 심볼 |
| `positionAmt` | 포지션 수량. 양수는 롱, 음수는 숏 |
| `entryPrice` | 평균 진입 가격 |
| `breakEvenPrice` | 손익분기점 가격 |
| `markPrice` | 마크 가격 |
| `unRealizedProfit` | 미실현 손익 |
| `liquidationPrice` | 청산 가격 |
| `leverage` | 레버리지 |
| `maxNotionalValue` | 허용 최대 명목 가치 |
| `marginType` | 마진 타입. `cross` 또는 `isolated` |
| `isolatedMargin` | 격리 마진 금액 |
| `isAutoAddMargin` | 자동 마진 추가 여부 |
| `positionSide` | 포지션 방향. `BOTH`, `LONG`, `SHORT` |
| `notional` | 명목 가치 |
| `isolatedWallet` | 격리 지갑 잔고 |
| `updateTime` | 업데이트 시간 |

각 필드는 포지션 관리 및 리스크 계산에 사용된다.

## 5. 심볼 거래 규칙 조회

### 5.1 Exchange Information

- HTTP method: `GET`
- Endpoint: `/fapi/v1/exchangeInfo`
- Purpose: 거래 가능한 심볼 목록과 각 심볼의 프리시전, 가격/수량 자리수, 주문 최소/최대 값 등을 조회한다.
- Request parameters: 없음

응답 주요 필드:

| 필드 | 설명 |
| --- | --- |
| `rateLimits` | 요청량 제한 정보 |
| `assets` | 마진으로 사용할 수 있는 자산 목록과 `marginAvailable` 값 |
| `symbols[]` | 각 심볼의 세부 정보 배열 |

`symbols[]` 주요 필드:

| 필드 | 설명 |
| --- | --- |
| `symbol` / `pair` | 심볼명 및 거래쌍 |
| `contractType` | 선물 유형. `PERPETUAL`, `CURRENT_MONTH` 등 |
| `status` | 거래 상태. `TRADING`, `BREAK` 등 |
| `baseAsset` / `quoteAsset` / `marginAsset` | 기준 자산, 가격 표시 자산, 마진 자산 |
| `pricePrecision` / `quantityPrecision` | 가격/수량 소수점 자리수 |
| `filters[]` | 주문 규칙 목록. `PRICE_FILTER`는 `tickSize`, `LOT_SIZE`는 `minQty`와 `stepSize`를 제공 |

주문 전 수량과 가격을 올바른 단위로 반올림하기 위해 `filters[]` 정보를 캐싱해야 한다.

## 6. 주문/계좌 실시간 스트림(User Data Stream)

Gptrader는 REST polling 대신 websocket stream으로 주문 체결, 포지션 변동, 잔고 변동을 실시간 반영해야 한다. Binance User Data Stream은 REST API로 listen key를 발급받고, 해당 key로 websocket에 연결한다.

### 6.1 Start User Data Stream

- HTTP method: `POST`
- Endpoint: `/fapi/v1/listenKey`
- Purpose: 새로운 User Data Stream을 시작하고 유효한 `listenKey`를 발급받는다.
- Parameters: 없음

응답 예시:

```json
{
  "listenKey": "pqia91ma19a5s61cv6a81va65sdf..."
}
```

발급된 key는 60분 동안 유효하다. 이 key로 websocket 연결을 생성한다.

### 6.2 Keepalive User Data Stream

- HTTP method: `PUT`
- Endpoint: `/fapi/v1/listenKey`
- Purpose: 기존 `listenKey`의 만료 시간을 연장한다. 60분마다 호출하여 스트림을 유지해야 한다.

응답 예시:

```json
{
  "listenKey": "3HBntNTepshgEdjIwSUI..."
}
```

### 6.3 Close User Data Stream

- HTTP method: `DELETE`
- Endpoint: `/fapi/v1/listenKey`
- Purpose: User Data Stream을 종료하고 listen key를 무효화한다.
- Parameters: 없음
- Response: 빈 객체 `{}` 반환

User Data Stream websocket URL:

```text
wss://fstream.binance.com/ws/<listenKey>
```

스트림 메시지 구조와 이벤트 타입, 예를 들어 `ORDER_TRADE_UPDATE`, `ACCOUNT_UPDATE` 등은 공식 문서를 참고한다.

## 7. 서버 시간/서명 보조

### 7.1 Check Server Time

- HTTP method: `GET`
- Endpoint: `/fapi/v1/time`
- Purpose: API 서버 시간을 조회하여 로컬 시간과의 오차를 보정한다. 서명에 사용되는 `timestamp`는 이 값을 기준으로 허용 범위 내에 있어야 한다.

응답 예시:

```json
{
  "serverTime": 1499827319559
}
```

## 8. 우선순위 및 구현 가이드

| 항목 | 구현 가이드 |
| --- | --- |
| 캔들 조회 | 전략 컨텍스트와 백테스트에서 가장 중요하다. `GET /fapi/v1/klines`를 사용하고 필요한 만큼 `limit`을 조절한다. |
| 주문 제출 | 실거래에서는 `POST /fapi/v1/order`로 시장가/지정가/조건부 주문을 생성한다. 응답에서 `orderId`와 `status`를 확인한다. |
| 주문/체결 이력 조회 | `GET /fapi/v1/allOrders`와 `GET /fapi/v1/userTrades`를 조합해 부분 체결, 취소 등 주문 상태를 복원한다. |
| 계좌/잔고 조회 | `GET /fapi/v2/balance`와 `GET /fapi/v2/account`로 잔고 및 포지션에 필요한 지표를 읽는다. |
| 포지션 조회 | `GET /fapi/v2/positionRisk`로 현재 포지션의 진입가격, 미실현 손익 등을 확인한다. |
| 심볼 거래 규칙 조회 | `GET /fapi/v1/exchangeInfo`를 호출해 가격/수량 스텝, 최소 주문금액 등의 규칙을 캐싱한다. |
| 실시간 스트림 | `POST /fapi/v1/listenKey`로 key를 발급받아 websocket에 연결하고, `PUT /fapi/v1/listenKey`로 주기적으로 갱신한다. REST 호출보다 빠르고 정확한 체결 정보를 제공한다. |
| 서버 시간 동기화 | 주문 서명 오류 방지를 위해 주기적으로 `GET /fapi/v1/time`으로 서버 시간을 조회한다. |

향후 변경 사항은 Binance Change Log에서 확인한다.
