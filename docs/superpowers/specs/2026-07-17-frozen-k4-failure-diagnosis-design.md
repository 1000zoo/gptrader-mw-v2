# Frozen K4 Failure Diagnosis Design

## Purpose

Explain, without changing or reselecting the model, why the frozen BTCUSDT
three-day K4 GMM recorded:

- `maximum_matched_centroid_distance = 2.3526219570607076`
- `maximum_distance_exceedance_rate = 0.04631322364411944`

This is a diagnostic replay of the already executed gate calculation. It is
not model development, gate calibration, strategy research, or a second chance
to pass the frozen model.

## Non-negotiable boundaries

The diagnostic may read only:

- the frozen failed-model attempt and its source provenance;
- BTCUSDT one-minute source archives needed to reproduce anchors from
  `2020-12-29T00:00:00Z` through `2025-06-30T00:00:00Z`;
- code and dependency metadata needed to reproduce the original calculation.

It must not read or construct:

- Strategy Mapping, Validation, Evidence, or Test data;
- candidate manifests or strategy ledgers;
- a replacement primary artifact;
- alternative K, covariance types, seeds, hyperparameters, or thresholds;
- rolling or expanding pseudo-OOS folds;
- block-bootstrap gate calibration.

The frozen primary clipping bounds, RobustScaler parameters, selected feature
order, feature registry, GMM parameters, confidence thresholds, and gate
thresholds are immutable inputs.

## Chosen architecture

Create a standalone script:

`scripts/diagnose_frozen_three_day_k4_failure.py`

The script uses focused pure diagnostic services. It does not extend the main
experiment orchestrator or the independent publication auditor. This keeps
integrity verification, experiment execution, and exploratory diagnosis as
separate responsibilities.

The script has four ordered stages:

1. verify immutable inputs and access boundaries;
2. reproduce the two original failure metrics independently;
3. stop on any reproduction mismatch, otherwise perform descriptive
   decomposition without further GMM fitting;
4. render, hash, validate, and atomically publish the run directory.

## Immutable identity manifest

Before fitting either diagnostic half, record:

- failed-model attempt hash and model-file SHA-256;
- canonical primary-model-parameter hash;
- canonical scaler hash over selected feature names, lower bounds, upper
  bounds, medians, and scales;
- clipping-bounds hash;
- canonical feature-registry/schema hash, including names, order, formulas,
  aggregation intervals, lookbacks, schema version, and float64 dtype;
- source archive descriptors and combined provenance hash;
- all 1,641 anchors, their window starts, canonical vector hashes, and the
  combined source-anchor-manifest hash;
- split timestamp and half-open ranges;
- GMM configuration, seed, initialization/convergence settings, and
  regularization;
- Python, NumPy, SciPy, scikit-learn, BLAS/LAPACK, CPU architecture, and
  thread-limit metadata.

The exact split is:

- Half A: `[2021-01-01T00:00:00Z, 2023-04-01T00:00:00Z)`, 820 anchors;
- Half B: `[2023-04-01T00:00:00Z, 2025-06-30T00:00:00Z)`, 821 anchors.

The diagnostic runs with `OMP_NUM_THREADS=1`, `MKL_NUM_THREADS=1`, and
`OPENBLAS_NUM_THREADS=1`. Environment metadata remains part of the report even
when a backend ignores a limit.

## Diagnostic-only half refits

Exactly two GMM fits are permitted: the same deterministic Half A and Half B
fits used by the original temporal gate. Each fit must use the original:

- raw feature rows and feature order;
- per-half p0.5/p99.5 clipping fit;
- per-half RobustScaler fit;
- retained feature names from the primary fit;
- K=4 diagonal GMM configuration;
- random seed, initialization count, convergence settings, and regularization.

These fits are marked `diagnostic_only=true`, are never written to the live
model registry, and cannot replace the primary model.

For each half preserve:

- clipping bounds, medians, and scales;
- means, diagonal covariances, weights, and precision information;
- convergence flag, iteration count, and lower bound;
- assignments and posterior probabilities;
- projected parameter centroids and projected diagonal covariances;
- empirical primary-space centroids;
- complete matching cost matrix and Hungarian assignment;
- per-pair distance and primary/half cluster shares.

## Coordinate projection

The original temporal gate compares each half model to the primary model in the
frozen primary standardized coordinate system.

For half component `h` and feature `j`, reproduce the original parameter
projection exactly:

```text
raw_mean[h,j] = half_mean[h,j] * half_scale[j] + half_median[j]
primary_projected_mean[h,j] =
    (raw_mean[h,j] - primary_median[j]) / primary_scale[j]
```

The original implementation projects component parameters. It does not clip
the inverse-transformed centroid again. This exact projected parameter centroid
is the only value used to reproduce `2.3526219570607076`.

Projected diagonal variance is:

```text
raw_variance[h,j] = half_variance[h,j] * half_scale[j]^2
primary_projected_variance[h,j] =
    raw_variance[h,j] / primary_scale[j]^2
```

As a descriptive comparison only, also transform the half's actual observations
with frozen primary clipping and scaling and compute an empirical primary-space
centroid for each reproduced half assignment. Differences between empirical and
parameter projections must be reported and must not alter reproduction status.

## Component identity and matching

Component indices are display metadata, never identity. Existing primary and
half fingerprints must be reproduced using the production canonical
fingerprinting rule over schema and fitted parameters. No rounding is allowed
before hashing; values are finite float64 in fixed feature order.

For each half:

1. build the Euclidean cost matrix between frozen primary means and projected
   half parameter means;
2. run the same Hungarian assignment;
3. preserve every matrix value and matched pair;
4. compute each matched Euclidean distance;
5. take the maximum across both halves and all matched pairs.

The failed pair identity is therefore:

```text
half
primary_component_fingerprint
half_component_fingerprint
primary_component_index
half_component_index
matching_cost
euclidean_distance
```

The metric is not a direct Half A-to-Half B centroid distance.

## Reproduction of the primary-model OOD rate

The OOD calculation is independent of the half-refit matching calculation.
Assign all 1,641 Cluster Development anchors to the frozen primary GMM.

For an anchor assigned to component `k`:

```text
squared_mahalanobis =
    sum_j((scaled_x[j] - primary_mean[k,j])^2 / primary_variance[k,j])
```

Use the original regularized diagonal covariance stored in the frozen model.
The threshold is the original chi-square 99.5th percentile with degrees of
freedom equal to the 25 retained features. An anchor exceeds only when
`squared_mahalanobis > threshold`; equality does not exceed.

Record:

- total anchors, valid anchors, excluded anchors, and exclusion reasons;
- integer exceedance numerator;
- denominator;
- computed rate;
- threshold, degrees of freedom, and comparison operator;
- assigned component, distance, and exceedance flag for every anchor.

The expected current count is not hard-coded separately from the expected rate;
the diagnostic derives it and verifies that `numerator / denominator` reproduces
the expected rate.

## Reproduction gate

The two paths are reported separately as:

- `temporal_half_refit_stability_reproduction`;
- `primary_model_ood_reproduction`.

For each expected/reproduced float record:

- `exact_bit_match` using packed IEEE-754 float64 bytes;
- `numeric_tolerance_match` using
  `math.isclose(reproduced, expected, rel_tol=1e-12, abs_tol=1e-12)`;
- expected value, reproduced value, absolute error, and relative error.

Both numeric tolerance matches are required before any decomposition runs. On
failure, classify the first verified cause among:

- `input-data-mismatch`;
- `split-boundary-mismatch`;
- `preprocessing-mismatch`;
- `dependency-version-nondeterminism`;
- `gmm-fitting-nondeterminism`;
- `projection-mismatch`;
- `matching-mismatch`;
- `original-metric-provenance-incomplete`.

The new value never replaces the published frozen result.

## Descriptive decomposition after successful reproduction

No GMM is fit after reproduction. All assignments and component parameters are
frozen to the reproduced primary and two half results.

### Cluster and feature drift

For every primary-to-half matched pair report:

- primary and half shares;
- projected Euclidean distance;
- per-feature delta, squared delta, and squared-distance contribution ratio;
- the five dominant Euclidean drift features;
- raw and primary-scaled distribution summaries for dominant features.

Distribution summaries include count, missing/inf count, mean, standard
deviation, skewness, kurtosis, minimum, p01, p05, p25, p50, p75, p95, p99,
maximum, clipping count, and lower/upper clipping direction.

### Robust location sensitivity

Within fixed reproduced assignments compare:

- arithmetic mean;
- coordinate-wise median;
- coordinate-wise 10% trimmed mean;
- Euclidean medoid in primary-scaled space.

This describes the assigned samples. It is not a refitted-model result.

### Clipping and extreme-sample sensitivity

The original reproduction includes all samples and original clipping behavior.
Afterward, with assignments fixed, recompute descriptive centroids after:

- excluding samples clipped on at least one frozen-primary feature;
- excluding the 1, 3, and 5 most distant samples;
- excluding the farthest 1% of samples, using deterministic anchor order to
  break ties.

Record clipped feature names/directions/count per sample and clipping rates per
half and cluster. Every sensitivity row contains:

- `assignment_source=frozen_reproduced_half_assignment`;
- `refit_after_exclusion=false`;
- `diagnostic_only=true`.

The result may only be described as a centroid-statistic sensitivity, never as
improved model stability.

### Component distribution distances

For each matched diagonal-Gaussian pair compute:

- Euclidean centroid distance;
- pooled diagonal Mahalanobis distance, with
  `pooled_variance = (primary_variance + half_variance) / 2`;
- symmetric KL divergence;
- Bhattacharyya distance;
- diagonal Gaussian Wasserstein-2 distance.

For pooled Mahalanobis, floor every pooled variance at the frozen model's
regularization `1e-6` and report per-feature
`delta^2 / pooled_variance` contributions.

### Cluster-specific OOD

Report primary-component share, exceedance numerator, denominator, rate, and
dominant distance-contribution features. Preserve every exceeding anchor in the
OOD sample CSV. Explicitly state whether the largest temporal centroid-drift
component and largest OOD-rate component are the same fingerprint.

### Spaced-anchor sensitivity

Do not fit another model. Subsample the fixed anchor assignments and descriptive
statistics using every offset:

- three-day spacing offsets `0, 1, 2`;
- seven-day spacing offsets `0, 1, 2, 3, 4, 5, 6`.

The first anchor in each half defines offset zero. Preserve each offset result;
do not average offsets or reinterpret them as gate outcomes.

## Outputs

Create an immutable run directory:

`docs/backtests/frozen_k4_failure_diagnosis/<run_id>/`

On successful reproduction it contains:

- `frozen_k4_failure_reproduction.json`;
- `frozen_k4_cluster_diagnostics.csv`;
- `frozen_k4_feature_contributions.csv`;
- `frozen_k4_ood_samples.csv`;
- `frozen_k4_distance_comparison.csv`;
- `frozen_k4_failure_diagnosis.md`;
- `manifest.json`, containing file hashes, status, and input identities.

The six named evidence files match the requested public artifacts; the manifest
is the publication envelope.

On reproduction failure, publish only:

- `frozen_k4_failure_reproduction.json`;
- `frozen_k4_failure_diagnosis.md`;
- `manifest.json`.

Generate everything under a temporary sibling directory, validate all schemas
and hashes, write the manifest last, then atomically rename the complete
directory. Never leave diagnostic CSVs from a failed run in a final directory.
The run ID is deterministic from the canonical input manifest, not wall-clock
time. Repeating the same inputs must produce byte-identical files and the same
run directory identity.

## Required report answers

The Markdown introduction must answer:

1. whether both failure metrics reproduced exactly or within tolerance;
2. which primary/half pair produced `2.3526`;
3. which features dominated that distance;
4. whether mean-only drift persists for median, trimmed mean, and medoid;
5. how much descriptive distance changes after clipping/extreme exclusions;
6. which components and features produce the `4.631%` OOD rate;
7. whether centroid drift and OOD concentrate in the same component/features;
8. whether covariance-aware distances confirm the anomaly;
9. whether conclusions persist across every three-day/seven-day offset;
10. whether evidence supports implementation error, tail sensitivity,
    feature-specific drift, component-specific drift, or broad structural drift.

The classification must cite measured evidence and may select multiple causes.
It cannot change model status, gate status, or authorize strategy research.

## Testing strategy

Use TDD for every production unit. Tests must cover:

- exact replay of the frozen primary/half projection and Hungarian matching;
- independent reproduction of both expected metrics;
- stop-before-decomposition behavior for each mismatch class;
- exact OOD numerator/denominator and strict `>` comparison;
- fingerprint/index permutation invariance;
- robust-location, clipping, extreme-removal, distance, and offset formulas;
- recursive rejection of Mapping, Validation, Evidence, candidate, and Test
  material;
- no registry mutation and no new primary artifact;
- deterministic CSV/JSON/Markdown bytes;
- failure and success atomic-directory publication with rollback;
- a real local-source integration fixture that executes both diagnostic half
  refits without touching later intervals.

Before publishing the real diagnosis, run it twice under the frozen single-
thread environment and compare all output hashes. Then run the repository test
suite and `git diff --check`.
