# Module P: `src/infrastructure/llm`

## 목적

LLM 전략이 사용할 외부 모델 호출 계층을 독립된 인프라 모듈로 정리한다.

## 책임

- LLM client adapter 구조 정의
- 프롬프트 조립 책임 분리
- 응답 파싱과 실패 번역 책임 분리

## 포함 범위

- `src/infrastructure/llm/llm_client.py`
- `src/infrastructure/llm/prompt_builder.py`
- `src/infrastructure/llm/response_parser.py`

## 제외 범위

- 전략 판단 도메인 규칙
- 모델 벤더 선택 로직의 상위 노출
- API 컨트롤러

## 선행 조건

- Module J
- LLM 전략 계약 정의

## 산출물

- LLM 포트 구현 기준
- 프롬프트와 응답 파싱 경계
- 실패 처리 규칙 초안

## 완료 기준

- domain과 application이 벤더 SDK를 모른다.
- 프롬프트 조립이 전략 구현에 섞이지 않는다.
- 응답 파싱 실패가 계약 언어로 번역된다.

## 다음 연결 모듈

- Module D
- Module E
