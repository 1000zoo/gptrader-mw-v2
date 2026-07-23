# Cluster Development Clusterability Feasibility Study Design

## 1. 목적

이번 연구는 특정 군집 모델을 고르는 연구가 아니다. 기존 BTCUSDT 3일 OHLCV
피처 공간에 시간 변화에도 반복되는 이산 군집 구조가 실제로 존재하는지 검정한다.

이전 pseudo-OOS 연구는 주어진 피처 공간에서 K-Means와 GMM 후보의 상대 안정성을
비교했고, 60개 후보 모두 절대 품질 기준을 통과하지 못해
`no_eligible_candidate`로 끝났다. 이번 연구는 그보다 앞선 질문을 다룬다.

> 이 데이터가 단일한 연속 분포 또는 타원형 heavy-tail 분포가 아니라, 재현 가능한
> K=2 또는 K=3의 분리 구조를 가진다는 증거가 있는가?

결과는 다음 셋 중 하나다.

- `clusterability_supported`
- `clusterability_not_supported`
- `inconclusive`

이 결과만으로 모델을 선택하거나 artifact를 만들지 않는다.

## 2. 금지 범위

다음 영역은 import, read, metric 계산, 의사결정에 사용하지 않는다.

- Strategy Mapping
- Strategy Evidence
- Validation
- Test
- outcome, PnL, strategy performance
- 기존 또는 신규 전략 후보

이번 연구에서는 qualification, gate calibration, runtime model artifact, freeze,
cash-only 규칙, 전략 연결도 수행하지 않는다. `clusterability_supported`가 나오더라도
별도의 피처 표현 및 모델 연구 설계 없이 다음 단계로 자동 진행하지 않는다.

## 3. 데이터 계약

### 3.1 시간 경계

- symbol: `BTCUSDT`
- source: Binance USD-M futures 1-minute klines
- raw candle interval: `[2020-12-29T00:00:00Z, 2025-06-30T00:00:00Z)`
- anchor interval: `[2021-01-01T00:00:00Z, 2025-06-30T00:00:00Z)`
- anchor frequency: 매일 00:00 UTC
- expected anchors: 1,641
- 각 anchor의 lookback: 정확히 직전 4,320분

2025-06-30 이후 데이터는 접근하지 않는다. 2020-12-29부터 2020-12-31까지는
첫 anchor 계산을 위한 lookback-only 구간이며 분석 표본이 아니다.

### 3.2 원천 데이터 무결성

분석 전에 다음을 모두 검증한다.

- canonical archive request 순서와 URL
- ZIP central-directory member identity
- archive SHA-256
- 정확히 2,367,360개의 연속된 1분 candle
- timestamp gap, duplicate, reversal 없음
- 모든 OHLCV가 finite
- `high >= max(open, close)`, `low <= min(open, close)`, `high >= low`
- volume은 0 이상
- anchor와 feature window의 정확한 개수 및 경계

하나라도 실패하면 formal 연구를 시작하지 않고 `inconclusive`로 종료한다.

## 4. 고정 피처 공간

feature schema는 `btc-chart-regime-ohlcv-3d-v1`을 재사용한다. fold 결과를 보고
피처를 추가·제거하거나 순서를 바꾸지 않는다.

### 4.1 `core25_v1`

다음 순서를 고정한다.

1. `return_4h`
2. `return_12h`
3. `return_1d`
4. `return_2d`
5. `return_3d`
6. `rv_4h`
7. `rv_1d`
8. `rv_3d`
9. `rv_ratio_1d_3d`
10. `range_ratio_3d`
11. `close_location_3d`
12. `directional_efficiency_1d`
13. `directional_efficiency_3d`
14. `sign_change_rate_1d`
15. `sign_change_rate_3d`
16. `return_autocorr_1d`
17. `return_autocorr_3d`
18. `max_drawdown_3d`
19. `max_runup_3d`
20. `breakout_rate_3d`
21. `mean_body_ratio_3d`
22. `mean_upper_wick_ratio_3d`
23. `mean_lower_wick_ratio_3d`
24. `volume_cv_3d`
25. `volume_ratio_1d_3d`

### 4.2 `dedup_vol_range22_v1`

`core25_v1`에서 다음 세 피처만 제거하고 나머지 순서를 유지한다.

- `rv_4h`
- `rv_3d`
- `range_ratio_3d`

이 후보는 frozen K4 진단 뒤 생성된 개발 가설이다. 독립적인 사전 피처 후보인 것처럼
표현하지 않는다. Mapping, Validation, Test 결과를 사용해 만든 후보는 아니다.

## 5. Fold 계약

기존 pseudo-OOS 연구와 직접 비교하기 위해 동일한 12개 quarterly origin과 두
train scheme을 사용한다.

- expanding train: `[2021-01-01, B)`
- rolling train: `[B - 18 calendar months, B)`
- purge: `[B, B + 3 days)`
- validation: `[B + 3 days, next origin)`
- 마지막 validation end: `2025-06-30`

| Fold | Origin B | Validation end | Expanding train | Rolling train | Purge | Validation |
|---:|---|---|---:|---:|---:|---:|
| 1 | 2022-07-01 | 2022-10-01 | 546 | 546 | 3 | 89 |
| 2 | 2022-10-01 | 2023-01-01 | 638 | 548 | 3 | 89 |
| 3 | 2023-01-01 | 2023-04-01 | 730 | 549 | 3 | 87 |
| 4 | 2023-04-01 | 2023-07-01 | 820 | 547 | 3 | 88 |
| 5 | 2023-07-01 | 2023-10-01 | 911 | 546 | 3 | 89 |
| 6 | 2023-10-01 | 2024-01-01 | 1,003 | 548 | 3 | 89 |
| 7 | 2024-01-01 | 2024-04-01 | 1,095 | 549 | 3 | 88 |
| 8 | 2024-04-01 | 2024-07-01 | 1,186 | 548 | 3 | 88 |
| 9 | 2024-07-01 | 2024-10-01 | 1,277 | 547 | 3 | 89 |
| 10 | 2024-10-01 | 2025-01-01 | 1,369 | 549 | 3 | 89 |
| 11 | 2025-01-01 | 2025-04-01 | 1,461 | 550 | 3 | 87 |
| 12 | 2025-04-01 | 2025-06-30 | 1,551 | 548 | 3 | 87 |

총 24개 fold context다. expanding은 primary evidence, rolling은 초기 역사 의존성을
줄인 stress evidence로 사용한다.

## 6. Fold별 전처리

각 fold와 feature set마다 pseudo-train에서만 다음을 fit한다.

1. feature별 p0.5/p99.5 clipping bounds
2. clipping
3. `RobustScaler` median과 IQR

pseudo-validation에는 위 값을 고정 적용한다. validation에서 clipping bound, center,
scale을 다시 fit하지 않는다.

PCA는 clusterability 판정 모델의 입력 변환으로 사용하지 않는다. PCA는 유효 차원과
거리 집중을 설명하는 descriptive diagnostic에만 사용하며 pseudo-train에서만 fit한다.
두 null family는 이 전처리가 끝난 train 좌표계에서 fit·생성하며 null 표본에
observed validation 정보를 사용하지 않는다.

## 7. Descriptive geometry diagnostics

각 fold와 feature set에서 다음을 기록한다.

- PCA eigenvalue spectrum
- 80%, 90%, 95% 누적 설명력에 필요한 component 수
- participation-ratio effective dimension:
  `(sum(lambda))^2 / sum(lambda^2)`
- 상위 10개 absolute feature correlation pair
- registry family별 within-family absolute correlation 중앙값과 최댓값
- 결정적 seed로 선택한 최대 10,000개 pair의 Euclidean distance
  coefficient of variation

이 지표들은 원인 설명에 사용하지만 단독으로 support 판정을 만들지 않는다.

## 8. Clusterability probe

### 8.1 Probe의 역할

K-Means는 최종 모델 후보가 아니라 공간의 분리 가능성을 측정하는 고정된 geometry
probe로만 사용한다.

- K: 2, 3
- initialization: `k-means++`
- `n_init=20`
- `max_iter=500`
- `tol=1e-4`
- deterministic root seed: `20260723`

평가 configuration은 정확히 네 개다.

1. `core25_v1`, K=2
2. `core25_v1`, K=3
3. `dedup_vol_range22_v1`, K=2
4. `dedup_vol_range22_v1`, K=3

상대 순위를 만들거나 이 중 하나를 선택하지 않는다.

### 8.2 Observed statistics

각 configuration/fold에서 train에 probe를 fit하고 validation에는 고정 predict한다.

- train cluster index:
  `sum(within-cluster squared distance) / total squared distance`
- fixed-predict validation silhouette
- train/validation component count와 share
- validation collapse:
  component count가 5 미만이거나 share가 5% 미만
- train과 validation의 prevalence total variation

silhouette는 validation에 두 개 이상의 component가 있고 각 component count가 2
이상일 때만 계산한다. collapse는 metric unavailable이 아니라 부정적 구조 증거다.

## 9. Null benchmark

heavy-tail 또는 상관된 단일 분포가 K-Means에 의해 임의로 나뉘는 효과와 실제 분리
구조를 구분하기 위해 두 null family를 사전 고정한다.

### 9.1 Covariance-matched Gaussian null

fold train의 Ledoit-Wolf covariance와 mean을 fit한다. 같은 train/validation 크기의
multivariate Gaussian 표본을 생성한다. observed와 동일한 probe fit/predict/metric
계산을 적용한다.

### 9.2 Radial heavy-tail elliptical null

fold train을 Ledoit-Wolf covariance로 whiten한다. empirical radial distance는
복원추출하고 방향은 unit sphere에서 균등 생성한 뒤 원래 covariance 공간으로
되돌린다. 이 null은 observed의 radial heavy-tail 규모를 보존하면서 방향성 군집
구조를 제거한다. validation null도 train에서 얻은 radial 분포만 사용한다.

### 9.3 Monte Carlo 계약

- null replicates: family별 499
- 각 replicate는 독립적인 deterministic child seed 사용
- primary statistic: fixed-predict validation silhouette
- 보조 statistic: train cluster index
- silhouette upper-tail Monte Carlo p-value:
  `(1 + count(null >= observed)) / 500`
- cluster-index lower-tail Monte Carlo p-value:
  `(1 + count(null <= observed)) / 500`

각 fold와 null family에서 statistic별로 네 configuration의 p-value에 Holm
correction을 적용해 family-wise alpha 0.05를 통제한다. 즉 silhouette 네 검정과
cluster-index 네 검정은 서로 분리된 Holm family다. 한 configuration의
`null_separation_pass`는 두 null family에서 다음이 모두 성립해야 한다.

- adjusted validation-silhouette p-value <= 0.05
- adjusted train-cluster-index p-value <= 0.05

Gaussian null만 이기고 radial heavy-tail null을 이기지 못한 경우 support로 판정하지
않는다.

## 10. Temporal block-bootstrap stability

overlapping 3-day window와 시간 자기상관을 무시한 iid bootstrap은 사용하지 않는다.

각 configuration/fold의 pseudo-train에서 다음을 수행한다.

- circular moving-block bootstrap
- block length: 28 daily anchors
- bootstrap refits: 100
- 각 bootstrap sample에서 clipping bounds와 RobustScaler를 새로 fit한 뒤 K-Means
  probe를 새로 fit
- 각 bootstrap model의 고유 전처리로 원래 fold train을 transform한 뒤 predict
- 100개 assignment 사이의 모든 pairwise ARI/NMI 계산

fold stability pass 기준:

- pairwise ARI p05 >= 0.80
- pairwise NMI p05 >= 0.80

0.80은 이전 후보 결과에 맞춰 새로 정한 값이 아니라, 이전 절대 품질 정책에서
모델 구조 안정성의 최소 기준으로 사전 고정했던 값이다.
28일 block은 3일 overlapping window와 7일 주기를 모두 포함하는 네 주 길이로
결과 확인 전에 고정한다.

## 11. 사전 고정 판정 규칙

### 11.1 Configuration-level support

한 configuration이 support를 받으려면 다음을 모두 만족해야 한다.

#### Expanding primary evidence

- 12 folds 중 최소 10 folds에서 `null_separation_pass`
- 12 folds 중 최소 10 folds에서 temporal stability pass
- 12 folds 전체에서 validation collapse 0
- 필수 metric unavailable 0

#### Rolling stress evidence

- 12 folds 중 최소 8 folds에서 `null_separation_pass`
- 12 folds 중 최소 8 folds에서 temporal stability pass
- 12 folds 전체에서 validation collapse 0
- 필수 metric unavailable 0

10/12는 primary expanding 역사 구간의 최소 83.3%에서 반복되는 증거를 요구하면서
최대 두 분기의 일시적 예외만 허용한다. 8/12는 고정 길이 rolling window의 더 큰
표본 변동성을 고려하되 최소 3분의 2에서 같은 방향을 요구한다. collapse 0 조건은
유효한 이산 구조라면 어느 평가 분기에서도 명목 component가 사실상 사라져서는 안
된다는 fail-closed 해석이다. 이 비율과 기준은 formal 결과 확인 전에 고정한다.

### 11.2 Study-level status

- `clusterability_supported`: 네 configuration 중 하나 이상이 모든 support 조건 통과
- `clusterability_not_supported`: formal run과 모든 metric이 완전하지만 통과
  configuration이 없음
- `inconclusive`: 데이터/경계/provenance/compute 완전성 실패, 또는 collapse 이외의
  이유로 필수 metric이 unavailable

통과 configuration이 여러 개여도 winner를 선택하거나 순위를 매기지 않는다.
K=2가 K=3보다 상대적으로 나아도 자동 fallback하지 않는다.

## 12. 계산 단계와 규모

### 12.1 Fixture

작은 synthetic 자료에서 다음을 검증한다.

- 명확한 2-cluster 자료는 support 방향
- 단일 Gaussian 자료는 not-supported 방향
- heavy-tail elliptical 자료가 radial null을 이기지 못함
- collapse와 metric unavailable 구분
- Holm correction과 최종 status golden case

fixture 결과로 configuration이나 threshold를 제거·변경하지 않는다.

### 12.2 Capability

첫 origin의 expanding/rolling context와 네 configuration에 대해 전체 코드 경로를
실행한다. null replicate와 bootstrap 수만 각각 9와 5로 줄여 실행 가능성, checkpoint,
resume, provenance를 확인한다. capability 결과는 formal 판정에 사용하지 않는다.

### 12.3 Formal

- base observed fits: `24 × 4 = 96`
- null fits: `24 × 4 × 2 × 499 = 95,808`
- bootstrap fits: `24 × 4 × 100 = 9,600`
- 총 K-Means fits: 105,504

fit은 content-addressed checkpoint로 저장하며 formal identity는 capability와 분리한다.
모든 job key에 terminal receipt가 있어야 aggregation을 시작한다.

## 13. Fail-closed 조건

다음 중 하나라도 발생하면 결과를 support/not-supported로 게시하지 않는다.

- 원천 archive, checksum, candle continuity 또는 anchor 수 불일치
- fold count/boundary/purge/count 불일치
- feature registry/order/hash 불일치
- validation-derived preprocessing
- 비고정 seed 또는 예상하지 않은 configuration
- NaN/Inf
- estimator non-convergence
- null covariance가 유효한 SPD로 regularize되지 않음
- 필수 observed/null/bootstrap receipt 누락·중복
- capability checkpoint가 formal namespace에 혼입
- forbidden data/module/path 접근
- manifest byte/hash 불일치
- 결과 계산 뒤 threshold, null family, block length 또는 판정 규칙 변경

collapse는 fail-closed 실행 오류가 아니라 configuration fail 증거로 기록한다.

## 14. 산출물

연구 결과는 runtime model artifact 경로와 분리된 새 deterministic run directory에
게시한다.

- `design_receipt.json`
- `data_access_receipt.json`
- `feature_sets.json`
- `folds.json`
- `geometry_diagnostics.csv`
- `observed_metrics.csv`
- `null_metrics.csv`
- `bootstrap_stability.csv`
- `configuration_decisions.json`
- `study_decision.json`
- `report.md`
- `manifest.json`

`study_decision.json`에는 configuration별 모든 조건의 numerator, denominator,
threshold, pass/fail을 기록한다. `report.md`는 결과 상태, 기하 진단, null 비교,
temporal stability, collapse 및 제한점을 요약한다.

model parameter, scaler, clipping bounds를 runtime-loadable artifact 형태로 게시하지
않으며 `selected_candidate`, `qualification`, `gate_calibration`, `freeze` 필드는
존재하지 않는다.

## 15. 테스트와 감사

최소 테스트 범위는 다음과 같다.

- exact data/fold boundary 및 3-day purge
- train-only clipping/scaling/PCA/null fit
- 두 null generator의 shape, determinism, covariance/radius 보존
- Monte Carlo p-value 방향과 Holm correction
- K-Means probe가 final-model selection API를 노출하지 않음
- validation collapse와 unavailable 구분
- 28-day circular block bootstrap determinism
- ARI/NMI p05 계산
- support/not-supported/inconclusive golden fixtures
- checkpoint resume와 terminal completeness
- forbidden-range/module/data-access guard
- manifest/hash/byte identity

formal 완료 뒤 별도의 독립 감사에서 raw receipt로부터 configuration 판정과 최종
status를 다시 계산해 게시 결과와 exact match해야 한다.

## 16. 다음 단계

`clusterability_supported`이면 이번 결과만으로 모델을 선택하지 않는다. 통과한 구조를
바탕으로 별도의 저차원 피처 표현 및 temporal model 비교 연구를 새로 설계한다.

`clusterability_not_supported`이면 기존 22/25차원 이산 군집 탐색을 중단하고,
독립 시장 축으로 만든 연속형 regime representation 연구로 전환한다.

`inconclusive`이면 원인을 수정한 뒤 동일 design identity로 재개하지 않고,
수정된 implementation identity와 별도 run identity로 다시 실행한다.
