# Clusterability feasibility 연구 결과

## 결론

BTCUSDT 3일 OHLCV의 `core25`·`dedup22` 피처와 K-Means K=2·3 조합에서는
시간 변화와 재표본화에 안정적인 이산 군집 구조가 지지되지 않았다.

최종 상태는 `clusterability_not_supported`이다. 모델 선택, artifact freeze,
Strategy Mapping은 수행하지 않았다.

## 최소 증거

- Cluster Development: 2021-01-01~2025-06-30
- 입력: 55개 checksum 검증 archive, 연속 1분봉 2,367,360개, daily anchor 1,641개
- formal jobs: 105,504/105,504
- unavailable metrics: 0
- 독립 audit: exit 0

| 후보 | null pass (expanding/rolling) | stability pass (expanding/rolling) | collapse folds | 결과 |
|---|---:|---:|---:|---|
| core25 K2 | 0/12 · 0/12 | 0/12 · 0/12 | 13 | unsupported |
| core25 K3 | 8/12 · 8/12 | 0/12 · 0/12 | 12 | unsupported |
| dedup22 K2 | 0/12 · 0/12 | 0/12 · 0/12 | 0 | unsupported |
| dedup22 K3 | 12/12 · 10/12 | 0/12 · 0/12 | 3 | unsupported |

- execution ID: `b6955a9273d3617721d2a31119c9c5e8faf8b743b75a8efd0bedbec8505a1b16`
- publication ID: `3342f153363d45f628d7614b1a4cb21393b7ab1463f83515982ee6e273516c25`
- terminal receipt root: `59b6ad7d4e377f58a36b115de1a92bcf787e1b8cbc0846c5bd0c7ed9761d77cc`
- manifest SHA-256: `ba94988b65de60b2d238336046c1a49aff2c4f0cdfcffad38ae4525beafba49d`

## 해석 한계와 다음 방향

이 결과는 시장 regime 자체의 부재를 증명하지 않는다. 현재 3일 피처와
K-Means형 이산 군집 가설이 안정적으로 재현되지 않았다는 뜻이다. 다음 탐색은
현재 기준을 완화하지 않고 연속 latent state, change-point, HMM 등 다른 상태
표현을 별도 가설로 검증한다.

원본 OHLCV와 공식 checksum은 후속 연구 입력으로 보존한다. 이번 연구의 코드,
테스트, checkpoint 및 상세 산출물은 이 기록으로 대체해 제거했다.
