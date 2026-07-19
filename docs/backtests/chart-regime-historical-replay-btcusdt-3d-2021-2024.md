# BTCUSDT 3-day regime historical replay

| Model | Clip share | Posterior tail | Margin tail | Distance tail | JSD | Min ESS | Quarterly warnings |
|---|---:|---:|---:|---:|---:|---:|---:|
| gmm-diag-k4 | 0.379121 | 0.054945 | 0.054945 | 0.032967 | 0.024638 | 82.35 | 3 |
| gmm-diag-k8 | 0.379121 | 0.089482 | 0.091837 | 0.054160 | 0.037603 | 84.26 | 5 |

## Training-reference tails

- gmm-diag-k4: posterior p05=0.757973, margin p05=0.517065; component distance uses training p99.5 (linear quantile).
- gmm-diag-k8: posterior p05=0.751616, margin p05=0.528208; component distance uses training p99.5 (linear quantile).

## Prevalence comparison

- gmm-diag-k4: training counts/shares={'0f705f28e5bf54678ca0ebe3': 116, '6d0d1affcd5a616a8daf784b': 188, '717c5b1f6e6900bf9f2a7d48': 187, 'baed8e58c11ce3b4f680e945': 236} / {'0f705f28e5bf54678ca0ebe3': 0.15955983493810177, '6d0d1affcd5a616a8daf784b': 0.2585969738651995, '717c5b1f6e6900bf9f2a7d48': 0.25722145804676755, 'baed8e58c11ce3b4f680e945': 0.3246217331499312}; historical counts/shares={'0f705f28e5bf54678ca0ebe3': 447, '6d0d1affcd5a616a8daf784b': 242, '717c5b1f6e6900bf9f2a7d48': 255, 'baed8e58c11ce3b4f680e945': 330} / {'0f705f28e5bf54678ca0ebe3': 0.35086342229199374, '6d0d1affcd5a616a8daf784b': 0.18995290423861852, '717c5b1f6e6900bf9f2a7d48': 0.2001569858712716, 'baed8e58c11ce3b4f680e945': 0.25902668759811615}; historical-training deltas={'0f705f28e5bf54678ca0ebe3': 0.19130358735389197, '6d0d1affcd5a616a8daf784b': -0.06864406962658096, '717c5b1f6e6900bf9f2a7d48': -0.057064472175495956, 'baed8e58c11ce3b4f680e945': -0.06559504555181506}.
- gmm-diag-k8: training counts/shares={'021cf5da658bbb8a891d3803': 104, '340255b9bb291b2c8bf6951c': 58, '4c135e31ff2eb6abf8897fc3': 83, '50a4d2af865d577c31b3c85f': 100, '7e2850f05408573738b5e3d5': 88, '98ee2ae3b65563954026199d': 86, 'be23e3975752ecc63885bc0d': 138, 'e27a95030541d7f7555832b9': 70} / {'021cf5da658bbb8a891d3803': 0.14305364511691884, '340255b9bb291b2c8bf6951c': 0.07977991746905089, '4c135e31ff2eb6abf8897fc3': 0.11416781292984869, '50a4d2af865d577c31b3c85f': 0.1375515818431912, '7e2850f05408573738b5e3d5': 0.12104539202200826, '98ee2ae3b65563954026199d': 0.11829436038514443, 'be23e3975752ecc63885bc0d': 0.18982118294360384, 'e27a95030541d7f7555832b9': 0.09628610729023383}; historical counts/shares={'021cf5da658bbb8a891d3803': 107, '340255b9bb291b2c8bf6951c': 116, '4c135e31ff2eb6abf8897fc3': 107, '50a4d2af865d577c31b3c85f': 82, '7e2850f05408573738b5e3d5': 211, '98ee2ae3b65563954026199d': 108, 'be23e3975752ecc63885bc0d': 198, 'e27a95030541d7f7555832b9': 345} / {'021cf5da658bbb8a891d3803': 0.08398744113029827, '340255b9bb291b2c8bf6951c': 0.09105180533751962, '4c135e31ff2eb6abf8897fc3': 0.08398744113029827, '50a4d2af865d577c31b3c85f': 0.06436420722135008, '7e2850f05408573738b5e3d5': 0.16562009419152277, '98ee2ae3b65563954026199d': 0.0847723704866562, 'be23e3975752ecc63885bc0d': 0.1554160125588697, 'e27a95030541d7f7555832b9': 0.2708006279434851}; historical-training deltas={'021cf5da658bbb8a891d3803': -0.059066203986620575, '340255b9bb291b2c8bf6951c': 0.011271887868468736, '4c135e31ff2eb6abf8897fc3': -0.030180371799550423, '50a4d2af865d577c31b3c85f': -0.0731873746218411, '7e2850f05408573738b5e3d5': 0.04457470216951451, '98ee2ae3b65563954026199d': -0.03352198989848823, 'be23e3975752ecc63885bc0d': -0.034405170384734146, 'e27a95030541d7f7555832b9': 0.17451452065325124}.

## Clipping and quarterly warnings

- gmm-diag-k4: pre-clipping envelope share=0.379121; clipped dimensions p50/p95/max=0.0/4.0/10.0; 14-quarter warnings: 2021-Q1 (zero=baed8e58c11ce3b4f680e945; concentrated=0f705f28e5bf54678ca0ebe3); 2021-Q2 (zero=none; concentrated=0f705f28e5bf54678ca0ebe3); 2023-Q3 (zero=none; concentrated=baed8e58c11ce3b4f680e945).
- gmm-diag-k8: pre-clipping envelope share=0.379121; clipped dimensions p50/p95/max=0.0/4.0/10.0; 14-quarter warnings: 2021-Q1 (zero=50a4d2af865d577c31b3c85f,98ee2ae3b65563954026199d,be23e3975752ecc63885bc0d; concentrated=e27a95030541d7f7555832b9); 2021-Q2 (zero=98ee2ae3b65563954026199d; concentrated=e27a95030541d7f7555832b9); 2021-Q3 (zero=98ee2ae3b65563954026199d; concentrated=none); 2021-Q4 (zero=98ee2ae3b65563954026199d; concentrated=none); 2022-Q1 (zero=98ee2ae3b65563954026199d; concentrated=none).

## Research preference

Preferred for research comparison only: **gmm-diag-k4**.
Rationale: lexicographic: clipping, margin-tail, distance-tail, empty-cluster quarter warnings, negative minimum ESS, JSD, K, identity.

## Limitations

- Reverse-time out-of-sample replay; it is not forward validation.
- Three-day feature windows overlap, so 1,274 rows are not independent; ESS and moving-block bootstrap are reported.
- Fourteen calendar quarters are inspected for empty or concentrated clusters.
- No strategy outcomes were read or evaluated.
- No runtime thresholds were created, no model was refit, and no production model was selected.
- Clipping, JSD, confidence tails, ESS, and quarter warnings are descriptive research diagnostics.
