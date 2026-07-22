# Cluster Development pseudo-OOS 군집 연구 요약

## 결론

- 최종 상태: `no_eligible_candidate`
- 60개 후보 모두 사전 고정한 절대 품질 조건의 AND 판정을 통과하지 못했다.
- 잠정 순위 1위인 `dedup_vol_range22_v1__gmm-diag-k3`와 비교 후보 `dedup_vol_range22_v1__gmm-spherical-k2`도 OOD 기준에서 탈락했다.
- 선택·qualification·gate calibration·artifact 생성·freeze·Strategy Mapping은 수행하지 않았다.
- K2로 자동 fallback하거나 관측 결과에 맞춰 OOD 기준을 완화하지 않았다.

## 실행 범위

- 데이터 경계: Cluster Development만 사용. Strategy, Mapping, Evidence, Validation, Test, outcome, performance 데이터는 접근하지 않았다.
- 데이터: BTCUSDT, 1,641 anchors, `[2021-01-01, 2025-06-30)`; candle 시작일은 `2020-12-29`.
- 후보: 2 feature sets × (GMM 4 covariance types + K-Means) × K 6개 = 60개.
- 검증: 24 pseudo-OOS folds × 20 independent seeds.
- formal fits: 28,800/28,800 완료, rejected 0.
- technical eligibility: 60/60. 절대 품질 판정: 0/60 통과.

## 고정 절대 품질 기준

모든 조건을 AND로 적용했고 metric unavailable은 fail-closed로 처리했다.

| 지표 | 통과 기준 |
| --- | ---: |
| p05 seed ARI | >= 0.80 |
| p05 seed NMI | >= 0.80 |
| minimum validation component share | >= 0.05 |
| maximum collapse fold count | 0 |
| maximum overall OOD rate | <= 0.05 |
| maximum component OOD rate | <= 0.10 |
| minimum OOD assignment coverage | 1.00 |
| maximum within-fold centroid distance | <= 0.50 |
| minimum covariance component coverage | 1.00 |

명목 train OOD는 component별 p99 기준으로 약 1%다. 전체 5%는 그 명목률의 5배, component 10%는 10배까지의 분포 변화를 허용하는 운영 상한으로 고정했으며, 현재 후보 결과를 본 뒤 조정하지 않았다.

## 주요 후보 결과

| 후보 | 잠정 점수 | aggregate overall OOD | maximum fold overall OOD | maximum component OOD | 판정 |
| --- | ---: | ---: | ---: | ---: | --- |
| `dedup_vol_range22_v1__gmm-diag-k3` | 0.186441 | 12.81% | 16.85% | 24.19% | OOD 두 기준 실패 |
| `dedup_vol_range22_v1__gmm-spherical-k2` | 0.181102 | 9.78% | 11.24% | 12.33% | OOD 두 기준 실패 |

두 후보의 다른 절대 품질 항목은 통과했지만, OOD 실패만으로도 AND 정책상 탈락이다. 낮은 상대 점수는 절대 품질 통과나 모델 선택을 의미하지 않는다.

## 연구 관찰

- `dedup22`는 `core25`와 짝지은 30개 구성 중 25개에서 상대 점수가 개선됐고 centroid drift와 OOD도 전반적으로 감소했다. 다만 seed 및 semantic 안정성 개선은 일관적이지 않아 확정 feature set으로 볼 수 없다.
- full covariance는 diag와 비교 가능한 12개 중 11개에서 점수가 악화했고, OOD·ARI/NMI·collapse·semantic fidelity도 대체로 나빠졌다. 기존 OOD가 diagonal covariance만의 문제라는 가설은 지지되지 않았다.
- K별 median collapse-fold rate는 K2 0%, K3 16.67%, K4 64.58%, K5 83.33%, K6 91.67%, K8 97.92%였다. 현재 fold 표본 크기에서는 K4 이상이 특히 불안정했다.
- 60개 중 collapse fold가 전혀 없는 후보는 8개뿐이었다.
- 이번 탐색에서 바로 freeze할 수 있는 군집 모델은 나오지 않았다. 다음 탐색은 현 정책을 결과에 맞춰 완화하는 방식이 아니라 feature 표현, OOD 정의 또는 군집 가정 자체를 새 가설로 세워야 한다.

## Provenance

- schema: `cluster-development-pseudo-oos-v1`
- final run ID: `4098c7cd45628568b4c46c457c370d224c85f0db721fa944ea5542f0b4420fde`
- implementation hash: `2b7f158e074255abd80e15a5eb8b7aa0412c72995c602151fe23801824bae39d`
- source provenance hash: `27e591699976a287c4ddd8d4bc4e34aff2fdcc650e5f8687e0a24fd9880e5353`
- absolute quality policy hash: `50f00b42e2069633e77626bfc55305b142eb6715b0c8f60c1b83e756606201c7`
- final manifest SHA-256: `3c08460cc2856a114fe81fde88b0e76b76a7c7e538aa9376849471e6aeada0c3`

## 보존 한계

이 문서는 연구 결론의 최소 기록이다. 전용 구현, 테스트, 설계·정책 문서, manifest, CSV/JSON, checkpoints 및 immutable run payload는 정리 과정에서 삭제했다. 따라서 위 hash는 과거 실행의 식별 정보일 뿐이며, 이 저장소 상태만으로 원시 결과를 재검산하거나 실행을 resume할 수 없다.
