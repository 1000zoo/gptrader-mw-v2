# Gptrader V3 Module Plan

이 문서는 `gptrader v3` 구현을 시작하기 전에 디렉토리와 책임을 먼저 고정하기 위한 작업 기준서다.
목표는 구현 순서를 강하게 묶지 않고, 각 모듈을 다른 세션에서 병렬로 진행할 수 있게 경계를 선명하게 나누는 것이다.

## 1. 작업 원칙

- `v2-backup`은 참고 자료다. 구조를 그대로 옮기지 않는다.
- 디렉토리 기준은 반드시 `docs/codex.md`를 따른다.
- 최상위 레이어는 `domain`, `application`, `infrastructure`, `interfaces`로 고정한다.
- 공통 모듈을 성급히 만들지 않는다. 책임이 선명한 경우에만 분리한다.
- 각 세션은 한 모듈만 책임지고, 다른 모듈 내부 구현은 건드리지 않는 것을 원칙으로 한다.
- 병렬 작업은 가능하지만, 계약이 먼저 없는 모듈은 구현하지 않는다.

## 2. 목표 디렉토리 구조

```text
src/
  domain/
    market/
    indicator/
    signal/
    strategy/
    signal_generator/
    risk/
    position/
    execution/
    lifecycle/
    ports/

  application/
    dto/
    usecases/
      trade/
      strategy_lifecycle/
      research/
    services/

  infrastructure/
    exchange/
      market_data/
      account/
      order_execution/
      position_stream/
    llm/
    persistence/
      repositories/
      models/
      migrations/
    messaging/
    config/

  interfaces/
    api/
    scheduler/
    websocket/
    cli/

  main.py
```

## 3. 레이어별 역할

### 3.1 `src/domain`

- 비즈니스 의미와 규칙만 가진다.
- 외부 API, DB, SDK, ORM을 모른다.
- 엔티티, 값 객체, 정책, 계산기, 포트 인터페이스를 가진다.

### 3.2 `src/application`

- 유스케이스 흐름만 조립한다.
- 입력 DTO를 받고 도메인과 포트를 호출한다.
- 인프라 예외를 직접 처리하지 않고 계약 언어로만 다룬다.

### 3.3 `src/infrastructure`

- 거래소, DB, LLM, 메신저, 설정, 외부 입출력을 구현한다.
- 상위 레이어에 필요한 포트를 실제 어댑터로 채운다.
- 외부 응답 형식과 재시도 정책은 이 레이어에 숨긴다.

### 3.4 `src/interfaces`

- FastAPI, 스케줄러, 웹소켓 리스너, CLI 같은 진입점을 둔다.
- 요청을 유스케이스 입력으로 변환하고 결과를 응답 형식으로 바꾼다.

## 4. 모듈 분해 원칙

세션을 나눌 때는 아래 순서를 지킨다.

1. `domain` 계약과 모델
2. `application` 유스케이스 경계
3. `infrastructure` 어댑터
4. `interfaces` 진입점

선행 계약이 없는 상태에서 아래 레이어를 먼저 구현하지 않는다.

## 5. 세션 분리용 모듈 목록

아래 모듈은 각각 독립 세션에서 진행할 수 있도록 나눈 1차 작업 단위다.
각 세션은 자신의 모듈 디렉토리와 직접 연결된 테스트 디렉토리만 책임지는 것을 기본으로 한다.

### Module A. `src/domain/market`

- 책임
  - 캔들, 심볼, 타임프레임, 시장 스냅샷 같은 시장 기본 모델 정의
  - OHLCV를 유스케이스와 전략이 공통으로 사용할 수 있게 표준화
- 포함 범위
  - `candle.py`
  - `symbol.py`
  - `timeframe.py`
  - `market_snapshot.py`
- 선행 의존성
  - 없음
- 병렬 가능 여부
  - 가능
- 비고
  - 다른 모든 도메인 모듈이 참조할 가능성이 높으므로 가장 먼저 고정한다.

### Module B. `src/domain/indicator`

- 책임
  - 지표 계산 입력/출력 모델 정의
  - 지표 계산 계약과 계산 엔진 경계 정의
- 포함 범위
  - `indicator_value.py`
  - `indicator_set.py`
  - `indicator_calculator.py`
- 선행 의존성
  - Module A
- 병렬 가능 여부
  - 부분 가능
- 비고
  - 전략 구현 전에 결과 모델이 먼저 안정돼야 한다.

### Module C. `src/domain/signal`

- 책임
  - 전략 판단 결과와 최종 매매 판단 모델 정의
  - `Signal`, `TradeDecision`, 판단 사유 모델 정리
- 포함 범위
  - `signal.py`
  - `signal_reason.py`
  - `trade_decision.py`
- 선행 의존성
  - 없음
- 병렬 가능 여부
  - 가능
- 비고
  - 전략, 집계기, 리스크 모듈의 공통 언어가 된다.

### Module D. `src/domain/strategy`

- 책임
  - 개별 전략 인터페이스와 전략 실행 입력 모델 정의
  - 단일 전략이 어떤 데이터를 받아 어떤 시그널을 반환하는지 고정
- 포함 범위
  - `strategy.py`
  - `strategy_context.py`
  - `strategy_result.py`
  - `implementations/`
- 선행 의존성
  - Module A
  - Module B
  - Module C
- 병렬 가능 여부
  - 계약 정의 후 구현은 병렬 가능
- 비고
  - `v2-backup/src/strategy/strategies`의 책임 분리는 참고하되 구조는 새로 만든다.

### Module E. `src/domain/signal_generator`

- 책임
  - 여러 전략 결과를 모아 최종 시그널을 만드는 상위 도메인 규칙 정의
  - 단일 전략, 복합 전략, 레짐 분기 전략의 공통 인터페이스 정의
- 포함 범위
  - `signal_generator.py`
  - `composite_signal_generator.py`
  - `regime_signal_generator.py`
- 선행 의존성
  - Module C
  - Module D
- 병렬 가능 여부
  - 부분 가능
- 비고
  - 전략 자체보다 상위 오케스트레이션이지만 아직 `application`이 아니라 `domain` 규칙이다.

### Module F. `src/domain/risk`

- 책임
  - 시그널 기반 포지션 크기, 레버리지, 진입 가능 여부 계산
  - 리스크 정책과 포지션 사이징 규칙 정의
- 포함 범위
  - `position_sizer.py`
  - `risk_policy.py`
  - `exposure_limit.py`
- 선행 의존성
  - Module C
- 병렬 가능 여부
  - 가능
- 비고
  - 계좌 조회 자체는 하지 않고, 필요한 계좌 상태는 입력 모델로만 받는다.

### Module G. `src/domain/position`

- 책임
  - 현재 포지션 상태, 포지션 이벤트, 상태 전이 규칙 정의
  - 웹소켓 이벤트 반영의 도메인 의미 정의
- 포함 범위
  - `position.py`
  - `position_event.py`
  - `position_status.py`
- 선행 의존성
  - Module C
- 병렬 가능 여부
  - 가능
- 비고
  - 실시간 추적과 후속 정산 로직의 중심 모델이다.

### Module H. `src/domain/execution`

- 책임
  - 주문 요청/응답 모델과 실행 결과의 도메인 표현 정의
  - 실제 거래소 SDK 타입이 아닌 상위 계약 언어를 만든다.
- 포함 범위
  - `order_request.py`
  - `order_result.py`
  - `execution_report.py`
- 선행 의존성
  - Module C
  - Module G
- 병렬 가능 여부
  - 가능
- 비고
  - 인프라의 주문 실행 어댑터가 이 모델을 구현 대상으로 삼는다.

### Module I. `src/domain/lifecycle`

- 책임
  - 전략 생성, 백테스트, 드라이런, 승격 상태를 표현하는 도메인 모델 정의
  - 전략 실험 수명주기 상태 전이 규칙 정리
- 포함 범위
  - `strategy_definition.py`
  - `signal_generator_definition.py`
  - `strategy_evaluation.py`
  - `promotion_policy.py`
- 선행 의존성
  - Module C
  - Module D
  - Module E
- 병렬 가능 여부
  - 부분 가능
- 비고
  - 저장소 설계와 직접 연결되므로 persistence 작업의 기준점이 된다.

### Module J. `src/domain/ports`

- 책임
  - 상위 레이어가 요구하는 저장소/외부 시스템 계약 정의
  - 시장 데이터 조회, 주문 실행, 포지션 조회, 전략 정의 저장 같은 포트를 명시
- 포함 범위
  - `market_data_port.py`
  - `account_port.py`
  - `order_execution_port.py`
  - `strategy_repository_port.py`
  - `signal_log_repository_port.py`
- 선행 의존성
  - 관련 도메인 모델들
- 병렬 가능 여부
  - 도메인 모델 고정 후 가능
- 비고
  - 병렬 세션을 가능하게 만드는 핵심 경계다.

### Module K. `src/application/usecases/trade`

- 책임
  - 실거래 실행 흐름 조립
  - 시장 데이터 조회, 지표 계산, 전략 실행, 리스크 검증, 주문 실행 순서 정의
- 포함 범위
  - `execute_trade_usecase.py`
  - `close_position_usecase.py`
  - `sync_position_usecase.py`
- 선행 의존성
  - Module A ~ J 중 거래 관련 계약
- 병렬 가능 여부
  - 계약 고정 후 가능
- 비고
  - `v2-backup/src/app/usecase/trade_execute_usecase.py`의 흐름은 참고하되, 직접 서비스 생성 방식은 금지한다.

### Module L. `src/application/usecases/research`

- 책임
  - 백테스트, 드라이런, 결과 평가 흐름 조립
  - 연구용 실행과 실거래 실행의 경계 분리
- 포함 범위
  - `backtest_strategy_usecase.py`
  - `dry_run_strategy_usecase.py`
  - `evaluate_strategy_usecase.py`
- 선행 의존성
  - Module B
  - Module C
  - Module D
  - Module E
  - Module I
  - Module J
- 병렬 가능 여부
  - 계약 고정 후 가능
- 비고
  - 실거래 유스케이스와 섞지 않는다.

### Module M. `src/application/usecases/strategy_lifecycle`

- 책임
  - 전략 등록부터 승격까지 전체 수명주기 유스케이스 조립
  - 자동화 정책은 여기서만 연결한다.
- 포함 범위
  - `register_strategy_usecase.py`
  - `promote_strategy_usecase.py`
  - `run_strategy_lifecycle_usecase.py`
- 선행 의존성
  - Module I
  - Module J
  - Module L
- 병렬 가능 여부
  - 부분 가능
- 비고
  - 연구 결과와 운영 배포 사이의 경계 역할을 한다.

### Module N. `src/infrastructure/exchange`

- 책임
  - 거래소별 시장 데이터 조회, 계좌 조회, 주문 실행, 포지션 스트림 어댑터 구현
  - Binance 같은 벤더 세부사항을 상위 레이어에서 숨긴다.
- 포함 범위
  - `market_data/`
  - `account/`
  - `order_execution/`
  - `position_stream/`
- 선행 의존성
  - Module J
  - 관련 도메인 모델
- 병렬 가능 여부
  - 하위 책임별 병렬 가능
- 비고
  - `v2-backup/src/binance/api`, `service`, `ws`는 책임 참조만 하고 그대로 복제하지 않는다.

### Module O. `src/infrastructure/persistence`

- 책임
  - 도메인 포트에 대한 DB 구현
  - 전략 정의, 시그널 로그, 평가 결과, 포지션 이벤트 저장
- 포함 범위
  - `repositories/`
  - `models/`
  - `migrations/`
- 선행 의존성
  - Module I
  - Module J
- 병렬 가능 여부
  - 모델 확정 후 가능
- 비고
  - `v2-backup/sql`은 테이블 아이디어만 참고한다.

### Module P. `src/infrastructure/llm`

- 책임
  - LLM 호출 어댑터 구현
  - 프롬프트 구성, 응답 파싱, 타임아웃, 재시도, 실패 번역 처리
- 포함 범위
  - `llm_client.py`
  - `prompt_builder.py`
  - `response_parser.py`
- 선행 의존성
  - Module J
  - LLM을 쓰는 전략 계약
- 병렬 가능 여부
  - 가능
- 비고
  - `domain`과 `application`은 LLM 벤더를 알면 안 된다.

### Module Q. `src/infrastructure/messaging`

- 책임
  - Slack, Telegram 등 알림 채널 어댑터 구현
  - 운영 이벤트를 표준 메시지 포맷으로 송신
- 포함 범위
  - `slack_notifier.py`
  - `telegram_notifier.py`
- 선행 의존성
  - 별도 알림 포트 정의
- 병렬 가능 여부
  - 가능
- 비고
  - 운영 보조 모듈이라 핵심 거래 흐름과 분리해서 진행 가능하다.

### Module R. `src/interfaces/api`

- 책임
  - 전략 등록, 실행 상태 조회, 운영 제어용 HTTP 진입점 제공
- 포함 범위
  - `strategy_controller.py`
  - `trade_controller.py`
  - `position_controller.py`
- 선행 의존성
  - 관련 application 유스케이스
- 병렬 가능 여부
  - 가능
- 비고
  - 비즈니스 로직은 금지한다.

### Module S. `src/interfaces/scheduler`

- 책임
  - 유스케이스 실행 스케줄 연결
  - 어떤 유스케이스를 언제 호출할지만 가진다.
- 포함 범위
  - `trade_scheduler.py`
  - `strategy_lifecycle_scheduler.py`
- 선행 의존성
  - Module K
  - Module M
- 병렬 가능 여부
  - 가능
- 비고
  - 스케줄러는 흐름 시작점일 뿐 판단 로직을 갖지 않는다.

### Module T. `src/interfaces/websocket`

- 책임
  - 거래소 포지션 이벤트를 수신해서 application 유스케이스로 전달
- 포함 범위
  - `position_listener.py`
  - `event_mapper.py`
- 선행 의존성
  - Module G
  - Module K
  - Module N
- 병렬 가능 여부
  - 부분 가능
- 비고
  - 웹소켓 프로토콜 상세는 `infrastructure`에 두고, 여기서는 진입점만 둔다.

## 6. 병렬 세션 우선순위

초기 병렬 세션은 아래 묶음으로 나누는 것이 가장 안전하다.

### Wave 1. 선행 도메인 고정

- Module A `domain/market`
- Module C `domain/signal`
- Module G `domain/position`

### Wave 2. 계산 규칙 고정

- Module B `domain/indicator`
- Module D `domain/strategy`
- Module F `domain/risk`
- Module H `domain/execution`

### Wave 3. 상위 도메인 계약 고정

- Module E `domain/signal_generator`
- Module I `domain/lifecycle`
- Module J `domain/ports`

### Wave 4. 유스케이스 분리

- Module K `application/usecases/trade`
- Module L `application/usecases/research`
- Module M `application/usecases/strategy_lifecycle`

### Wave 5. 어댑터와 진입점

- Module N `infrastructure/exchange`
- Module O `infrastructure/persistence`
- Module P `infrastructure/llm`
- Module Q `infrastructure/messaging`
- Module R `interfaces/api`
- Module S `interfaces/scheduler`
- Module T `interfaces/websocket`

## 7. 세션별 작업 규칙

- 한 세션은 한 모듈만 소유한다.
- 다른 모듈의 공개 계약을 바꿔야 하면, 해당 변경은 별도 계약 세션에서 먼저 확정한다.
- `v2-backup` 참고 시에는 책임과 도메인 의미만 가져오고, 파일 구조와 객체 생성 방식은 버린다.
- `Service`, `Helper`, `Util` 같은 포괄 이름은 피한다.
- 먼저 구현할 것은 코드가 아니라 계약과 책임이다.

## 8. 다음 시작점

가장 먼저 시작할 세션은 아래 셋이다.

1. `src/domain/market`
2. `src/domain/signal`
3. `src/domain/position`

이 셋이 고정되면 이후 세션에서 전략, 리스크, 실행, 저장소 계약을 안전하게 분리할 수 있다.
