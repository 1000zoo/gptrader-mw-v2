# Module F Risk Design

## 목적

`src/domain/risk`는 전략 판단을 실제 진입 가능 여부와 포지션 크기로 바꾸는 순수 도메인 규칙을 제공한다.
계좌 조회, 주문 전송, 저장소 접근은 포함하지 않는다.

## 설계 결정

Module F는 책임을 세 파일로 분리한다.

- `exposure_limit.py`: 계좌 잔고, 현재 노출, 심볼별/전체 노출 한도를 표현하고 신규 노출 가능 여부를 계산한다.
- `risk_policy.py`: `TradeDecision`과 리스크 입력을 받아 허용/차단 결과와 차단 사유를 만든다.
- `position_sizer.py`: `TradeDecision`의 신뢰도와 계좌 입력을 바탕으로 목표 포지션 명목 금액과 수량을 계산한다.

이 구조는 Module K가 거래 유스케이스를 조립할 때 리스크 판단과 크기 계산을 독립적으로 호출할 수 있게 한다.
또한 정책, 한도, 사이징 규칙을 각각 단위 테스트로 고정할 수 있다.

## 주요 모델

- `ExposureLimit`
  - `equity`: 계좌 평가 금액
  - `current_total_exposure`: 현재 전체 명목 노출
  - `current_symbol_exposure`: 현재 대상 심볼 명목 노출
  - `max_total_exposure_ratio`: 전체 노출 한도 비율
  - `max_symbol_exposure_ratio`: 심볼별 노출 한도 비율
- `RiskCheck`
  - `allowed`: 진입 가능 여부
  - `reason`: 허용 또는 차단 사유
- `PositionSize`
  - `notional`: 목표 명목 금액
  - `quantity`: 가격 기준 환산 수량

## 검증 방향

- 한도 계산은 음수 입력과 0 이하 equity를 거부한다.
- HOLD/EXIT 결정은 신규 진입 리스크를 통과하지 않는다.
- 신규 진입이 전체 또는 심볼 한도를 넘으면 명확한 사유로 차단된다.
- 신뢰도 기반 사이징은 `equity * base_risk_ratio * confidence * leverage`를 기준으로 계산한다.
