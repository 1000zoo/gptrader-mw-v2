# Cluster Development Pseudo-OOS 군집 모델 선택 설계

## 1. 목적과 완료 조건

이 파이프라인의 목적은 `BTCUSDT` 3일 일별 regime 군집 모델을 Strategy 성과와 완전히 분리한 상태에서 시간 변화, OOD, seed 변화에 대한 안정성만으로 선택하는 것이다.

설계의 완료 조건은 다음과 같다.

- Cluster Development 내부의 과거 정보만 사용하는 pseudo-OOS fold가 고정되어 있다.
- 각 fold에서 pseudo-train 전처리와 모델을 새로 fit하고 pseudo-validation에는 고정 적용한다.
- 후보 grid, seed, feature set, metric, 탈락 조건, 점수식, tie-break가 결과를 보기 전에 고정되어 있다.
- gate는 선택된 후보의 pseudo-OOS 역사 분포만으로 산출한다.
- 선택이 끝날 때까지 load 가능한 새 모델 artifact를 만들지 않는다.
- 어떤 Strategy Mapping, Strategy Evidence, Validation, Test 데이터나 성과도 읽지 않는다.
- 절대 품질 정책이 사전에 승인되지 않은 run은 순위를 만들 수 있어도 `ranked_but_not_qualified`에서 멈춘다.

이 설계는 모델 선택까지만 다룬다. 전략 후보 생성, 수익률, 손익, 거래 비용, Mapping, Evidence, Validation, Test는 명시적인 비범위다.

## 2. 접근안 비교와 결정

### 접근 A: expanding fold만 사용

12개 분기 validation origin마다 2021-01-01부터 직전 경계까지 누적 학습한다. 최종 full-development fit과 가장 비슷하고 계산량이 14,400 fits로 가장 작다. 그러나 오래된 관측치가 최근 구조 변화를 희석하는지 확인할 수 없다.

### 접근 B: expanding + 18개월 rolling 병행 — 채택

같은 12개 validation 구간에 expanding과 18개월 rolling pseudo-train을 각각 적용한다. expanding은 최종 누적 fit을 모사하고 rolling은 최근 국면만 사용했을 때의 민감도를 stress-test한다. 두 방식에서 동일 후보가 안정적인지를 직접 확인할 수 있으며 총 28,800 fits가 필요하다.

### 접근 C: 연 단위 validation

표본이 큰 3~4개 validation fold만 사용한다. 계산은 가장 싸고 component별 covariance 추정은 쉽지만, p95/p05 gate를 만들 역사 관측치가 너무 적고 일부 시작 시점에만 발생하는 불안정을 놓칠 가능성이 크다.

따라서 접근 B를 고정한다. rolling과 expanding은 서로 대체하지 않으며 동일한 validation anchors를 공유하는 두 개의 독립 학습 관점이다. 실행 비용을 통제하기 위해 capability 검증과 정식 selection run을 분리하되, 검증 결과로 후보를 제거하거나 정식 grid를 변경할 수 없다.

## 3. 데이터 접근 경계

### 3.1 허용 범위

- symbol: `BTCUSDT`
- feature schema: `btc-chart-regime-ohlcv-3d-v1`
- Cluster Development anchors: `[2021-01-01T00:00:00Z, 2025-06-30T00:00:00Z)`
- anchor 수: 정확히 1,641개, UTC 일별 단조 증가
- 첫 anchor의 3일 feature window를 만들기 위한 lookback-only raw candles: `[2020-12-29T00:00:00Z, 2021-01-01T00:00:00Z)`

lookback-only 구간은 feature 계산에만 사용할 수 있고 train/validation anchor가 될 수 없다. `2025-06-30T00:00:00Z` 이후 데이터 요청은 한 건이라도 발생하면 전체 run을 중단한다.

### 3.2 금지 범위

- Strategy Mapping 단계의 데이터, 코드 경로, 결과
- Strategy Evidence 단계의 데이터와 결과
- Validation 및 untouched Test 구간과 결과
- following-period outcome, 전략 수익률, PnL, Sharpe, drawdown, 거래 비용
- 기존 frozen K4의 성공/실패에 맞춘 threshold 조정

파이프라인의 데이터-access receipt에는 실제 요청한 최소/최대 candle timestamp와 anchor timestamp를 기록한다. 허용 범위를 벗어난 요청, 금지 필드의 report 유입, 금지 모듈 의존은 fail-closed다.

## 4. Fold 계약

### 4.1 공통 규칙

각 origin `B`에 대해 두 scheme을 만든다.

- expanding train: `[2021-01-01, B)`
- rolling train: `[B - 18 calendar months, B)`
- purge: `[B, B + 3 days)`
- validation: `[B + 3 days, next_origin)`

마지막 validation의 end는 `2025-06-30`이다. 3일 purge는 train의 마지막 3일 feature windows와 validation의 첫 feature window가 raw candles를 공유하지 않도록 한다. purge anchors는 어느 metric에도 포함하지 않는다.

각 fold의 pseudo-train에서만 아래 항목을 fit한다.

1. feature set 선택 — 사전 고정된 이름 목록 선택만 수행하며 data-driven pruning은 금지
2. feature별 p0.5/p99.5 clipping bounds
3. `RobustScaler` center와 scale
4. K-Means 또는 GMM parameters
5. component별 pseudo-train OOD distance p99 threshold

pseudo-validation에는 위 값을 변경하지 않고 clip, transform, predict만 수행한다. validation을 이용한 refit, threshold 수정, component 재학습은 금지한다.

### 4.2 고정 origin과 표본 수

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

표의 수치는 daily anchor 수다. 구현은 날짜를 재계산한 뒤 이 수치와 exact match해야 하며 다르면 run을 시작하지 않는다.

## 5. Feature 후보

Feature set은 결과 계산 전에 이름, 순서, registry/schema hash와 함께 고정한다. fold별 correlation pruning은 하지 않는다. 그러면 서로 다른 fold의 centroid가 같은 의미의 축을 유지한다.

### 5.1 `core25_v1`

기존 frozen K4가 사용한 25개 retained feature를 registry 순서 그대로 사용한다.

`return_4h`, `return_12h`, `return_1d`, `return_2d`, `return_3d`, `rv_4h`, `rv_1d`, `rv_3d`, `rv_ratio_1d_3d`, `range_ratio_3d`, `close_location_3d`, `directional_efficiency_1d`, `directional_efficiency_3d`, `sign_change_rate_1d`, `sign_change_rate_3d`, `return_autocorr_1d`, `return_autocorr_3d`, `max_drawdown_3d`, `max_runup_3d`, `breakout_rate_3d`, `mean_body_ratio_3d`, `mean_upper_wick_ratio_3d`, `mean_lower_wick_ratio_3d`, `volume_cv_3d`, `volume_ratio_1d_3d`.

28개 registry 중 기존 규칙으로 이미 제외된 `atr_ratio_1d`, `atr_ratio_3d`, `top_decile_volume_share_3d`는 다시 넣지 않는다.

### 5.2 `dedup_vol_range22_v1`

`core25_v1`에서 다음 세 항목만 사전 제거한다.

- `rv_4h`: 단기 절대 변동성 중복 제거
- `rv_3d`: 장기 절대 변동성 중복 제거
- `range_ratio_3d`: 절대 변동성 수준과 중복될 수 있는 range 수준 제거

축소안은 절대 변동성 수준 `rv_1d`, term-structure `rv_ratio_1d_3d`, range 내 위치 `close_location_3d`를 남긴다. 다른 family는 건드리지 않는다. 결과를 본 뒤 제거 목록을 바꾸거나 제3의 feature set을 추가하지 않는다.

이 feature set은 frozen K4 진단에서 변동성·range 계열 drift가 반복 관찰된 뒤 생성된 개발 가설이다. 무관한 사전 가설로 표현하지 않는다. 다만 후보 정의와 비교는 Cluster Development 내부에서만 수행하며 Mapping, Validation, Test 또는 전략 성과의 영향을 받지 않았다.

## 6. 모델 후보와 seed

K는 `2, 3, 4, 5, 6, 8`로 고정한다.

- GMM: K 6개 × covariance `diag`, `tied`, `full`, `spherical` = 24 구조
- K-Means: K 6개 = 6 구조
- feature set 2개를 적용한 총 후보 수 = `(24 + 6) × 2 = 60`

seed는 정수 `20260720`부터 `20260739`까지 정확히 20개를 사용한다. 구조·seed 안정성 grid의 각 fit은 `n_init=1`로 실행하여 seed 하나를 독립 관측치로 남긴다. 라이브/runtime artifact 타입의 현재 K 및 covariance 제약을 완화하지 않고, 이 grid는 research-only candidate config로 표현한다.

GMM의 `reg_covar=1e-6`, 수렴 tolerance, 최대 iteration, initialization 방식과 K-Means의 initialization 및 최대 iteration은 candidate registry에 한 번 고정한다. 수렴 실패 후 parameter를 완화한 자동 재시도는 금지한다.

상대 순위와 사전 승인된 절대 품질 기준을 모두 통과한 후보만 별도 qualification pass에 들어간다. qualification은 후보의 representative seed를 RNG root로 사용하되 GMM과 K-Means 모두 `n_init=20`으로 24개 fold context를 다시 fit한다. qualification gate와 최종 full-development freeze도 동일한 `n_init=20` 계약을 사용한다. 따라서 seed 안정성 관찰용 `n_init=1` 결과를 운영 fit 결과인 것처럼 freeze하지 않는다. qualification에는 24 fits가 추가된다.

## 7. 단계별 실행과 계산량

### 7.1 Capability 검증 단계

정식 결과를 만들기 전에 다음 두 검증을 수행한다.

1. synthetic contract fixture: 60 candidates × sentinel seeds `{20260720, 20260739}` = 120 fits
2. real-data capability check: 첫 2 origins × 2 schemes × 60 candidates × 같은 sentinel seeds 2개 = 480 fits

최대 600 fits의 capability 검증은 shape, covariance type, K=2, preprocessing isolation, metric availability, serialization과 resource estimate만 확인한다. 결과는 selection score, gate, 후보 제거에 사용할 수 없다. capability와 formal checkpoint namespace를 분리하고 formal 단계는 겹치는 480 real-data fits도 다시 계산한다. capability 결과를 이유로 정식 candidate registry를 변경하려면 이 설계를 새 version으로 다시 승인해야 한다.

### 7.2 정식 selection 단계

고정 workload는 다음과 같다.

- fold contexts: 12 origins × 2 schemes = 24
- candidate structures: 60
- seeds: 20
- 총 fit: `24 × 60 × 20 = 28,800`
- GMM fits: `24 × 48 × 20 = 23,040`
- K-Means fits: `24 × 12 × 20 = 5,760`
- seed pair: 후보/fold당 `20 choose 2 = 190`
- ARI/NMI pair 비교: 지표별 `24 × 60 × 190 = 273,600`

실행 단위는 `(fold_scheme, fold_origin, feature_set, model_type, covariance_type, K, seed)`의 immutable job이다. job은 독립적으로 병렬 실행할 수 있지만 BLAS thread는 worker당 1개로 고정해 이중 병렬화를 막는다.

각 job receipt는 input/config/code hash를 key로 content-addressed checkpoint에 원자적으로 저장한다. 중단 후 재실행은 hash가 완전히 일치하고 receipt 검증에 성공한 completed/rejected job만 재사용할 수 있다. 후보 자체의 convergence 또는 수치 실패는 rejected job으로 집계하며 전체 run을 폐기하지 않는다. 반면 grid job key 누락, 데이터 경계 위반, schema/manifest 손상, resource 중단처럼 결과 완전성을 보장할 수 없는 상태에서는 선택을 금지한다. 28,800개 모든 key가 completed 또는 rejected terminal receipt를 가져야만 집계를 시작한다.

## 8. 공통 비교 공간과 component 정렬

### 8.1 공통 reference 공간

Feature set별 공통 reference transform은 가장 이른 expanding pseudo-train `[2021-01-01, 2022-07-01)`에서만 fit한다. reference는 p0.5/p99.5 bounds와 RobustScaler center/scale을 가진 비교 전용 receipt이며 assignment나 모델 fit에 사용하지 않는다.

각 fold의 fitted centroid를 다음 순서로 투영한다.

1. fold-scaled centroid를 fold scaler로 inverse transform해 원본 feature 단위로 복원
2. 원본 centroid에서 공통 reference median을 빼고 reference scale로 나눔

covariance는 fold scale의 대각행렬로 원본 단위로 되돌린 뒤 reference scale로 congruence transform한다. spherical/diag/tied/full 모두 최종적으로 공통 공간의 full matrix 표현을 사용한다.

centroid projection에는 reference clipping을 다시 적용하지 않는다. 그래야 earliest bounds를 벗어난 실제 drift가 포화되어 숨지 않는다. 이 방식은 미래 fold 정보를 reference에 사용하지 않으며, 서로 다른 fold의 scale 변화와 centroid 변화가 섞이지 않게 한다. 원본 단위 centroid도 함께 저장해 feature 의미 해석에 사용한다.

최초 reference 의존성을 분리하기 위해 centroid distance는 두 계열로 저장한다.

- `within_fold_scaled_empirical_centroid_distance`: 각 fold의 train scaler 좌표에서 train fitted centroid와 validation empirical centroid를 비교하고 feature 수로 나눈 값
- `earliest_reference_centroid_distance`: 서로 다른 fold의 centroids를 최초 공통 reference 공간에서 비교한 값

Primary score에는 첫 번째 within-fold distance만 사용한다. earliest-reference distance와 successive-fold distance는 장기 좌표 이동 및 설명용이며 primary score와 절대 qualification 기준에 넣지 않는다.

### 8.2 정렬

- 같은 fold 안의 train component와 validation empirical component는 fitted assignment identity를 그대로 사용한다.
- seed 간 component는 같은 fold의 가장 작은 seed를 기준으로 common-reference centroid Hungarian matching한다.
- fold 간 component는 후보별 첫 expanding fold의 대표-seed centroids를 canonical reference로 삼아 직접 Hungarian matching한다. 연쇄 matching은 오류 누적 때문에 사용하지 않는다.
- cost는 component별 common-reference centroid squared Euclidean distance다.
- matching relative margin은 `(second_best_cost - best_cost) / max(abs(best_cost), 1e-12)`로 정의한다.
- relative margin이 `0.05` 미만이면 정렬이 실질적으로 비식별적이므로 해당 matching을 `unavailable`로 표시한다. second-best cost는 최적 assignment의 각 선택 edge를 하나씩 금지하고 Hungarian을 다시 실행한 결과 중 최소값으로 구하며 permutation을 brute-force하지 않는다.

후보별 `matching_coverage`는 요구된 seed/fold matching 중 relative margin을 통과한 비율이다. unavailable matching을 identity로 간주하거나 semantic metric에서 조용히 제외하지 않는다.

fingerprint는 model parameters의 hash와 별도로 `(candidate_id, fold_id, seed, aligned_component_index, common_reference_hash)`를 포함한다. report의 모든 component metric에는 fingerprint와 aligned index를 함께 기록한다.

## 9. Metric 정의

모든 metric은 train과 validation을 분리해 저장하고, 전체값과 component별 값을 모두 기록한다.

### 9.1 Centroid drift

- primary within-fold pseudo-OOS drift: fitted train centroid와 고정 assignment로 계산한 validation empirical centroid의 fold-scaled squared Euclidean distance를 feature 수로 정규화
- earliest-reference drift: common-reference 공간에서의 장기 비교용 squared Euclidean distance
- maximum, median, component별 distance
- successive-fold fitted centroid drift와 earliest-reference semantic drift
- distance의 feature별 squared contribution과 상위 5개 feature

### 9.2 Covariance drift

train과 validation assigned samples를 common-reference 공간에 놓고 deterministic Ledoit-Wolf covariance를 계산한다. GMM은 fitted covariance와 train empirical covariance를 모두 보존한다. drift는 ridge `1e-9 I`를 더한 SPD matrix의 normalized log-Euclidean distance `||log(A)-log(B)||F / sqrt(d)`로 정의한다.

component 표본이 2개 미만이면 해당 component의 covariance drift만 `unavailable`로 기록한다. assignment, prevalence, OOD와 계산 가능한 다른 component metric은 유지하며 job 전체를 거부하지 않는다. component 표본이 5개 미만이면 covariance 계산 가능 여부와 별개로 `component_collapse=true`를 기록한다.

fold covariance summary는 available components의 maximum/median과 `covariance_component_coverage = available_component_count / K`를 함께 가진다. unavailable을 0 drift로 대체하지 않는다. Primary score의 covariance 항목은 drift loss와 coverage loss를 각각 절반씩 반영한다.

### 9.3 군집 비중과 collapse

- component share train/validation
- total-variation prevalence drift: `0.5 × sum(abs(p_val - p_train))`
- 최소 component share와 최대 component share
- empty component count
- validation component count가 5 미만이면 collapse

대표 seed의 fold별 collapse component 수와 24개 context 중 collapse가 발생한 fold 수를 기록한다. collapse만으로 technical job 또는 candidate를 즉시 거부하지 않고, assignment 구조 불안정 metric과 절대 품질 정책의 입력으로 사용한다. empty component에서도 가능한 전체 OOD와 prevalence metric은 유지하되 해당 component의 empirical centroid, covariance, component OOD rate는 unavailable로 기록한다.

### 9.4 OOD

pseudo-train에서 각 component에 assign된 sample의 distance p99를 component threshold로 fit한다.

- GMM: covariance type에 맞는 squared Mahalanobis distance
- K-Means: squared Euclidean distance
- validation: assigned component threshold를 초과한 numerator/denominator/rate
- overall rate와 maximum component rate를 별도 기록
- pseudo-train assigned sample이 없어 threshold를 만들 수 없는 component는 threshold와 component rate를 unavailable로 기록
- `ood_assignment_coverage`: 정의된 component threshold로 판정할 수 있었던 validation assignments / 전체 validation assignments

overall OOD rate는 covered assignments의 numerator/denominator와 coverage를 항상 함께 제시한다. uncovered assignment를 정상 또는 OOD로 impute하지 않는다. validation을 이용한 distance threshold 재추정은 금지한다. clipping 전 bound exceedance rate도 별도 보조 지표로 저장해 clipping이 tail을 숨기는지 확인한다.

### 9.5 Assignment confidence와 margin

- GMM: maximum posterior와 top-1 minus top-2 posterior margin
- K-Means: pseudo-train에서 component별 assigned squared-distance median `m_j`를 fit하고 각 centroid까지의 squared distance를 `q_j = d_j^2 / max(m_j, 1e-12)`로 정규화한다. `exp(-q_j)` 정규화 값은 descriptive `normalized_distance_softmax_*`로만 기록하고 probability라고 부르지 않는다.
- K-Means ambiguity metric: 가장 작은 두 normalized distances의 `normalized_distance_margin = (q_2 - q_1) / max(q_2, 1e-12)`
- median, p05, ambiguous candidate rate를 저장

K-Means 값을 posterior라고 부르지 않는다. 서로 정의가 다른 confidence를 GMM과 K-Means 사이의 primary 점수에 직접 섞지 않는다. K-Means가 qualification 대상이면 운영 ambiguity gate에는 softmax 값이 아니라 normalized-distance margin만 사용한다.

### 9.6 Seed 안정성 및 label switching

- 같은 candidate/fold의 20 seeds 모든 pair에 대해 validation assignment ARI와 NMI
- median과 p05 ARI/NMI
- Hungarian permutation이 identity가 아닌 비율
- matching cost와 최적/차선 cost margin
- seed별 collapse, convergence failure, component share 분산

먼저 24개 fold context에서 모두 valid한 seed만 globally-valid seed로 정의한다. 후보의 representative seed는 globally-valid seeds 중 모든 fold context에 대한 다른 globally-valid seed와의 평균 ARI가 가장 높은 seed다. 동률이면 평균 NMI가 높은 seed, 다시 동률이면 숫자가 작은 seed를 선택한다. 이 규칙은 후보별로 한 seed를 고정하며 fold마다 seed를 바꾸지 않는다.

### 9.7 Temporal duration과 switching

daily argmax assignment sequence에서 다음을 계산한다.

- regime run length의 median, p25, p75, p95
- one-day regime 비율
- switching rate: 인접 anchor assignment가 바뀐 횟수 / 가능한 전이 수
- train 대비 validation의 switching-rate absolute drift
- validation/train median-duration log ratio의 절대값

분기 경계를 넘겨 run length를 연결하지 않는다. overlapping 3일 windows 때문에 이를 독립 표본 수나 유의성 검정으로 해석하지 않는다.

### 9.8 원본 feature 의미 유지

aligned component별 원본 feature centroid를 common-reference z profile로 표현한다.

- within-fold train profile과 validation empirical profile의 Pearson correlation
- earliest fold profile과의 descriptive Pearson correlation
- `abs(z) >= 0.5`인 salient feature의 sign agreement
- top-5 absolute profile feature의 Jaccard overlap
- registry family별 centroid contribution

평균 correlation, 최소 correlation, sign agreement, top-5 overlap을 기록한다. Primary score에는 within-fold correlation과 sign agreement만 사용하며 earliest-reference semantic 값은 descriptive로 제한한다. component 명칭은 자동으로 경제적 의미를 붙이지 않고 fingerprint와 상위 원본 feature만 보고한다.

## 10. 기술적 fail-closed 조건

### 10.1 전체 run 중단

- 허용 시간 범위 밖 candle, anchor, 파일 또는 dataset 접근
- 1,641 anchor, fold boundary, purge count, feature registry/hash 불일치
- 중복/역순/non-UTC anchor 또는 incomplete 3-day window
- feature set 이름/순서/hash가 precommitted registry와 불일치
- validation 값이 clipping/scaler/model/OOD threshold fit에 유입
- common reference가 최초 expanding train 외 데이터로 fit됨
- job key 중복, 결과 누락, manifest/hash 불일치
- 결과 계산 후 candidate registry, seed, metric, weight, tie-break 변경
- compute budget 초과 또는 중단으로 terminal receipt가 일부 grid에 없음. 이 경우 verified checkpoint는 보존하지만 run은 `incomplete`이며 집계·선택·publish를 금지

### 10.2 job 거부

- non-finite feature, bound, scale, probability, distance, metric
- clipping bound width 또는 RobustScaler scale이 0 이하
- model non-convergence 또는 maximum iteration 도달
- GMM covariance 비대칭, non-SPD, regularization floor 위반
- probability 합/순서 오류 또는 assignment 누락
- count와 무관하게 계산 가능해야 하는 필수 assignment/OOD/prevalence 값의 누락 또는 비정상 값

component count 때문에 정의할 수 없는 centroid/covariance/component OOD/matching은 metric-level `unavailable`이며 job rejection이 아니다. 거부 job의 metric은 대체하거나 impute하지 않는다.

### 10.3 candidate 탈락

- 24개 fold context에서 모두 valid한 globally-valid seed가 18/20 미만
- representative seed가 하나의 fold context라도 거부됨
- candidate score에 필요한 전체 assignment, prevalence, overall OOD, seed ARI/NMI가 누락됨

모든 후보가 기술적으로 탈락하면 selection status는 `no_eligible_candidate`다. threshold를 완화하거나 가장 덜 나쁜 후보를 강제 선택하지 않으며 모델 artifact를 만들지 않는다.

## 11. 결과 확인 전에 고정하는 모델 선택 규칙

### 11.1 Primary score

기술적으로 탈락하지 않은 후보만 비교한다. 각 metric은 후보별로 24 fold contexts의 representative-seed 값을 집계한다. 손실 metric은 p95, 이득 metric은 p05를 사용한 뒤 비교 후보 사이에서 `[0, 1]` percentile loss rank로 변환한다. 동률에는 average rank를 부여하고, 비교 후보가 하나뿐이면 모든 rank를 `0.0`으로 둔다. 낮을수록 좋다. relative rank는 후보 grid에 종속된 비교값이며 절대 품질 판정으로 해석하지 않는다.

| Domain | Weight | 입력 |
|---|---:|---|
| centroid/covariance 안정성 | 25% | within-fold max centroid drift 12.5%, covariance drift 6.25%, covariance coverage 6.25% |
| 비중/collapse 안정성 | 20% | prevalence TV drift 7%, minimum share 7%, collapse-fold rate 6% |
| OOD | 15% | overall OOD 5%, maximum component OOD 5%, OOD assignment coverage 5% |
| seed 안정성 | 20% | p05 ARI 10%, p05 NMI 10% |
| temporal 안정성 | 10% | switching drift 5%, duration log-ratio 5% |
| 원본 feature 의미 유지 | 10% | within-fold semantic correlation 3.5%, salient-sign agreement 3.5%, matching coverage 3% |

Primary score는 위 loss rank의 가중합이다. confidence와 margin은 모델-native scale이 달라 primary cross-family score에 넣지 않고 report 및 선택 후 gate calibration에 사용한다. BIC, likelihood, silhouette은 descriptive output일 뿐 선택 점수에 넣지 않는다.

metric-level unavailable은 0이나 중앙값으로 impute하지 않는다. covariance는 명시된 coverage loss로 반영하고, component-level OOD unavailable은 minimum share와 collapse-fold rate가 별도로 불이익을 포착하게 한다. candidate 전체에서 집계 metric을 계산할 관측치가 하나도 없으면 해당 loss rank를 `1.0`으로 고정한다.

### 11.2 Tie-break

최저 primary score와 절대 차이가 `0.01` 이하인 후보를 tie group으로 정의하고 아래 순서로 하나를 고른다.

1. 여섯 domain 중 최악 percentile loss rank가 낮은 후보
2. 22-feature 후보
3. 총 free parameter 수가 적은 후보
4. K가 작은 후보
5. p05 seed ARI가 높은 후보
6. canonical candidate id가 사전식으로 앞선 후보

GMM free parameter 수는 means, mixture weights, covariance parameters의 합이며 covariance type별 실제 자유도를 사용한다. K-Means는 centroid parameter 수를 사용한다. 선택 규칙이나 `0.01` tie band는 결과 확인 후 바꾸지 않는다.

### 11.3 절대 최소 품질 정책

상대 순위 1등만으로 모델을 선택하지 않는다. 정식 selection run이 자동 선택을 허용하려면 run 시작 전에 별도 `absolute_quality_policy`가 존재해야 하며 policy version, threshold 값, 근거 문서와 hash가 candidate registry와 run_id에 포함되어야 한다.

정책은 최소한 다음 기준을 모두 가져야 한다.

- `p05_seed_ari_min`
- `p05_seed_nmi_min`
- `minimum_validation_component_share_min`
- `maximum_collapse_fold_count`
- `maximum_overall_ood_rate`
- `maximum_component_ood_rate`
- `minimum_ood_assignment_coverage`
- `maximum_within_fold_centroid_distance`
- `minimum_covariance_component_coverage`

구체적인 숫자는 현재 설계에서 임의로 만들지 않는다. 별도로 승인된 Cluster Development pseudo-OOS baseline run에서만 정하고, 이 formal leaderboard를 본 뒤 같은 run에 소급 적용할 수 없다. Mapping 이후 자료나 외부 성과 기준은 근거로 사용할 수 없다.

- policy가 없으면 기술적으로 유효한 후보의 provisional ranking만 만들고 status를 `ranked_but_not_qualified`로 고정한다.
- policy가 있으면 절대 기준을 모두 통과한 후보만 qualified ranking에 들어간다.
- 절대 기준을 통과한 후보가 없으면 `no_eligible_candidate`다.
- 한 후보만 남아 percentile rank가 모두 0이더라도 절대 기준 통과가 선택의 필수 조건이다.

qualified ranking의 1위 후보만 `n_init=20` qualification pass를 수행한다. seed ARI/NMI 기준은 `n_init=1` 구조 안정성 grid에서 이미 판정했으므로 qualification에서 재계산하지 않는다. 나머지 centroid, covariance coverage, share, collapse, OOD, temporal, semantic 기준은 24개 qualification folds에서 다시 통과해야 status가 `selected`가 된다. 실패하면 차순위 후보로 자동 fallback하지 않고 `no_eligible_candidate`로 종료한다.

## 12. Gate calibration

모델 후보가 절대 품질 정책과 `n_init=20` qualification을 통과한 뒤, 아직 full-development 모델을 fit하기 전에 qualification fold 결과만 사용한다. `n_init=1` seed-stability grid의 gate를 운영 threshold로 재사용하지 않는다.

- high-side fold gate: `max(expanding p95, rolling p95)`
- low-side fold gate: `min(expanding p05, rolling p05)`
- quantile method: NumPy-compatible linear interpolation로 고정
- 대상: within-fold maximum centroid drift, maximum covariance drift와 covariance coverage, prevalence TV drift, minimum share, overall/max-component OOD와 OOD assignment coverage, switching drift, duration drift
- GMM sample ambiguity: 중복 validation을 피하기 위해 expanding validation assignments만 pool하여 maximum posterior p05와 posterior margin p05
- K-Means sample ambiguity: 같은 방식으로 normalized-distance margin p05. normalized distance softmax는 gate에 사용하지 않음

각 fold-level gate record에는 threshold만 저장하지 않고 다음 provenance를 함께 저장한다.

- expanding raw values 12개와 rolling raw values 12개
- scheme별 p95/p05, maximum, minimum, median, MAD
- p95/p05 linear interpolation에 사용된 두 order-statistic folds와 interpolation weights
- maximum을 만든 fold
- 최종 threshold를 지배한 scheme

gate threshold를 계산할 fold 수가 scheme별 12개가 아니거나 expanding pooled validation anchor가 기대 집합과 다르면 calibration을 거부한다. 현재 frozen K4의 `0.5`, `2%`, 관측 실패값 또는 후속 구간 결과는 calibration에 사용하지 않는다.

## 13. 산출물과 provenance

### 13.1 선택 run

새 `diagnostic_schema_version`과 입력/config/code hash에서 계산한 deterministic `run_id`를 사용한다. 기존 immutable directory는 절대 수정하지 않는다.

선택 run의 논리 산출물은 다음과 같다.

- `design_receipt.json`: 이 문서 hash와 금지 범위
- `data_access_receipt.json`: 실제 candle/anchor 접근 범위와 source hashes
- `feature_sets.json`: exact names, registry family, schema/hash
- `folds.json`: 24 contexts와 anchor hashes
- `candidate_registry.json`: 60 candidates, 20 seeds, estimator parameters
- `fit_receipts.jsonl`: 28,800 job status, input hash, convergence, parameter fingerprint
- `fold_metrics.csv`: sample/component/fold metrics
- `seed_stability.csv`: ARI/NMI와 matching receipts
- `candidate_summary.json`: eligibility와 precommitted score 입력
- `leaderboard.csv`: score, domain ranks, rejection reason
- `absolute_quality_policy.json`: optional precommitted 절대 기준, 근거와 hash. 없으면 명시적 null receipt
- `qualification_receipts.jsonl`: qualified ranking 1위 후보의 24개 `n_init=20` fold fits. qualification 미실행 시 사유 receipt
- `gate_calibration.json`: qualification 역사 원시값, 분포 요약, 지배 fold/scheme와 고정 thresholds
- `selection_receipt.json`: `ranked_but_not_qualified`, `selected` 또는 `no_eligible_candidate`, 절대 기준과 tie-break trace
- `report.md`: 최소 사람이 읽을 수 있는 결론
- `manifest.json`: 파일별 SHA-256, implementation hash, parent input hashes

모든 JSON은 canonical serialization을 사용하고 write는 staging directory 후 atomic publish한다. 부분 run directory는 성공 artifact로 게시하지 않는다.

### 13.2 선택 후 freeze

`selection_receipt.status == "selected"`, 절대 품질 policy hash, `n_init=20` qualification과 manifest 검증이 모두 성공한 뒤에만 별도의 deterministic freeze run을 시작할 수 있다. 그때 선택된 feature set, model config, representative seed를 RNG root로 사용하고 qualification과 동일한 `n_init=20` 계약으로 1,641 Cluster Development anchors 전체에서 clipping, RobustScaler, model, OOD threshold를 한 번 fit한다.

freeze artifact에는 feature 목록/순서와 registry hash, preprocessing parameters, K/covariance, `n_init`, model parameters, posterior 또는 normalized-distance-margin ambiguity thresholds, OOD thresholds, monitoring gates, component fingerprints, implementation hash, source/fold/qualification/selection receipt hashes를 포함한다. 선택 run 자체에는 runtime-loadable model artifact를 넣지 않는다.

## 14. 검증 전략

구현 시 다음 계약을 자동 테스트해야 한다.

- exact 1,641 anchors와 24 fold contexts
- 3일 purge가 raw candle overlap을 제거함
- capability 단계가 정확히 600 fits 이하이고 그 결과로 candidate registry를 변경할 수 없음
- verified checkpoint resume와 28,800 terminal job-key completeness
- validation 변조가 train bounds/scaler/model/OOD threshold를 바꾸지 않음
- validation 변조는 validation metrics만 바꿈
- common-reference projection round trip과 covariance congruence transform
- primary within-fold distance와 descriptive earliest-reference distance 분리
- four GMM covariance shapes와 K=2 포함 research-only config
- 60 candidates, 20 seeds, 28,800 unique job keys
- component count 2/5 경계에서 covariance unavailable, collapse, job validity가 독립적으로 변함
- Hungarian relative margin `0.05`, matching unavailable/coverage와 fingerprint 안정성
- OOD numerator/denominator, posterior와 K-Means confidence 명칭 분리
- K-Means component distance normalization과 normalized-distance margin
- score와 tie-break golden fixture
- policy 부재 시 `ranked_but_not_qualified`, 절대 기준 실패 시 no-selection 및 artifact 부재
- `n_init=1` seed grid와 `n_init=20` qualification/freeze 계약 분리
- gate raw 12+12 values, median/MAD, interpolation folds와 지배 scheme provenance
- forbidden range/module/data access 즉시 실패
- 동일 입력/config/code에서 byte-identical outputs와 동일 run_id

## 15. 설계상 제한

- validation 분기는 독립 표본이 아니며 expanding/rolling은 같은 validation anchors를 공유한다. quantile을 통계적 신뢰구간으로 해석하지 않는다.
- 87~89개 validation anchors에서 K=8 component covariance는 표본이 작을 수 있다. Ledoit-Wolf와 collapse 표시로 이를 숨기지 않고 선택 불이익으로 반영한다.
- common reference는 비교 좌표계일 뿐 production preprocessing이 아니다.
- feature 축소 후보는 두 개만 비교한다. 결과가 불만족스럽더라도 같은 run에서 feature set을 추가하지 않는다.
- 이 설계와 선택 결과는 전략 수익성을 말하지 않는다.
