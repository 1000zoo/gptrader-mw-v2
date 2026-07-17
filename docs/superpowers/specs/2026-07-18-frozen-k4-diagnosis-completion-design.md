# Frozen K4 Diagnosis Completion Design

## Purpose

Complete the two missing descriptive analyses in the reproduced frozen K4
failure diagnosis without changing, refitting, rematching, or re-evaluating the
frozen model. The completed report must identify how features contribute to the
24 Component 0 OOD exceedances and determine whether the full-sample drift and
OOD conclusions persist across every 3-day and 7-day offset subsample.

This work ends the frozen K4 cause diagnosis. It does not implement pseudo-OOS
validation, redesign gates, compare model candidates, alter features, freeze a
new model, or resume strategy mapping.

## Non-negotiable boundaries

Every offset analysis reuses the following existing values exactly:

- frozen primary clipping bounds, RobustScaler, and diagonal GMM;
- reproduced Half A and Half B GMM parameters;
- existing Hungarian component matches;
- existing half assignments and primary assignments;
- existing OOD squared Mahalanobis distances and component thresholds.

The implementation must not perform any offset-specific clipping fit, scaler
fit, GMM fit, component rematch, model artifact creation, gate re-evaluation, or
strategy-related calculation. The output remains diagnostic-only.

## Architecture

The existing frozen replay remains unchanged. New immutable result contracts
and pure aggregations are added to the post-reproduction decomposition service.
The renderer writes normalized CSV outputs, an extended reproduction JSON and
Markdown report, and a new deterministic manifest into a new immutable run
directory.

The already published diagnosis directory and every byte under it are immutable
inputs. They must not be modified, replaced, or supplemented. The extension has
a new `diagnostic_schema_version`; its deterministic `run_id` is derived from
the extension's canonical identity payload and therefore resolves to a distinct
directory. The new manifest records the prior run ID and manifest hash as parent
provenance without copying or rewriting the prior run.

The decomposition receives the same 1,641 ordered feature vectors, frozen
primary fit, reproduced half fits, fixed matches, assignments, and OOD rows as
the current successful diagnostic. It derives no new fitted state.

## Component 0 OOD feature analysis

### Population and contributions

The analysis population is exactly the existing 24 strict OOD exceedances
assigned to frozen primary Component 0. For every sample and retained feature,
reuse the existing diagonal squared Mahalanobis contribution:

`(primary_scaled_value - component_mean)^2 / component_variance`

The component variance retains the existing `1e-6` floor. The sum of feature
contributions must reproduce each stored squared Mahalanobis distance within the
existing numerical tolerance.

This analysis has explicit scope `primary-component-0-ood-exceedances`, and
every output row records `primary_component_index=0`. For every retained
feature, record:

- contribution sum;
- ratio of the feature sum to the contribution sum across all 24 samples;
- mean contribution per OOD sample;
- median contribution per OOD sample;
- top-1 occurrence count and ratio;
- top-5 occurrence count and ratio;
- global rank.

Per-sample top-feature ordering uses contribution descending, then frozen
registry order as the deterministic tie-break. The report displays the global
top five without filtering by family.

### Family analysis and fixed decisions

Feature families come only from `THREE_DAY_CHART_FEATURE_REGISTRY_V1`. The
volatility family is strictly the retained features whose registry family is
`volatility`:

- `rv_4h`;
- `rv_1d`;
- `rv_3d`;
- `rv_ratio_1d_3d`.

`range_ratio_3d` remains in `range`, and `volume_cv_3d` remains in `volume`.
Every registry family represented by the retained feature set is emitted even
when its aggregate contribution is zero.

The following thresholds are fixed before result calculation:

- `single_feature_concentration` is true when the largest single-feature total
  contribution ratio is at least `0.50`;
- `volatility_family_concentration` is true when the strict volatility-family
  aggregate contribution ratio is at least `0.70`;
- `recurrent_feature_dominance` is true when any feature has a top-1 occurrence
  ratio of at least `0.50`.

These are independent flags, not a mutually exclusive cause label. The report
must use the sum, median, and top-1/top-5 recurrence together to distinguish a
few extreme samples from a contribution repeated across the population.

### Registry provenance

Create a canonical registry payload from the full ordered V1 registry entries,
including schema version, name, family, aggregation minutes, lookback minutes,
and formula. Hash the canonical UTF-8 JSON payload with SHA-256. OOD feature and
family outputs record the schema version and registry hash. Family output also
records family contribution sum, ratio, applicable concentration threshold, and
concentration result. Feature output records feature name and registry family.

## Full-sample and offset empirical analysis

### Selection

Use the existing anchor array in its verified chronological order. For spacing
`s` in `{3, 7}` and each offset `o` in `[0, s)`, select positions satisfying
`index % s == o`. Record the first full-sample anchor as the offset origin so the
selection rule is independently reproducible.

No rows are reassigned. Each selected row keeps its existing half membership,
half assignment, primary assignment, and OOD result.

### Empirical centroid drift

Project each selected raw vector using the frozen primary clipping bounds and
RobustScaler. Group selected rows by half and the primary component matched to
their fixed half assignment. The group arithmetic mean in this frozen primary
coordinate system is the offset empirical centroid.

Compare that centroid with the corresponding frozen primary parameter centroid
using Euclidean distance. Name this metric
`offset_empirical_centroid_distance` everywhere to distinguish it from the
existing fitted-parameter centroid distance. Feature contributions are the
squared coordinate differences, whose sum must reproduce the squared empirical
centroid distance.

A group with no selected samples has status `insufficient_sample`, no centroid
or distance, and is excluded from maximum-drift selection. A one-sample group is
valid descriptive output and retains its explicit sample count. Maximum drift
ties are resolved by half label, primary component index, then half component
index.

For each valid half/component group, record selected count and its share of all
selected rows in that half. For each offset, record its maximum drift pair and
the pair's top five feature contributions.

Before computing offset comparisons, apply this identical empirical-centroid
procedure to all 1,641 rows without subsampling. Name the resulting reference
metric `full_sample_empirical_centroid_distance`. It uses the same frozen
primary coordinate projection, fixed half assignments, fixed Hungarian match,
grouping, arithmetic mean, Euclidean distance, and feature-contribution formula
as the offset metric. This full-sample empirical result is the primary reference
for subsample stability comparisons.

### OOD aggregation

For each offset and every frozen primary component, aggregate the already stored
OOD rows into numerator, denominator, and rate. A represented component with no
exceedances records a zero numerator and rate. A component with no selected
assigned samples records a zero denominator, a null rate, and cannot be the
maximum OOD component. Maximum-rate ties are resolved by larger numerator,
larger denominator, then lower component index.

### Full-sample consistency

The directly comparable immutable full-sample empirical references are:

- the maximum `full_sample_empirical_centroid_distance` component and pair;
- the existing maximum OOD component;
- the top five full-sample empirical drift features for the maximum empirical
  pair.

The existing fitted-parameter maximum drift pair and its top features remain in
the report as a separately named diagnostic. They are not used as the direct
offset stability comparator. The report may state whether the full-sample
empirical and fitted-parameter conclusions agree, but it must not conflate the
two metrics.

Every offset records:

- whether its maximum empirical drift primary component matches the full-sample
  maximum drift component;
- whether its maximum OOD component matches the full-sample maximum OOD
  component;
- whether its ordered top five drift features exactly match;
- whether its top-five feature set matches regardless of order.

The Markdown summary reports matching offsets over valid offsets separately for
3-day and 7-day spacing. It must explicitly state whether a conclusion is
universal, mixed across offsets, or confined to a subset. The comparison is
descriptive only and cannot pass or fail a model gate.

## Outputs

Publish these normalized deterministic files under the new schema-versioned run
directory and include them in its new manifest:

- `frozen_k4_component_0_ood_feature_summary.csv`;
- `frozen_k4_component_0_ood_family_summary.csv`;
- `frozen_k4_offset_empirical_diagnostics.csv`;
- `frozen_k4_offset_feature_contributions.csv`.

The new reproduction JSON gains structured OOD concentration,
full-sample-empirical, and offset-consistency sections. The new Markdown report
contains the completed Component 0 and offset answers with the computed top
features, family totals, three concentration flags, full-sample empirical
reference, offset maxima, and agreement counts. It does not replace or edit the
prior JSON or Markdown. Existing sample-level and diagnostic files remain
available in the parent run and retain their exact bytes and meaning.

Every Component 0 OOD CSV and JSON object records `analysis_scope` and
`primary_component_index=0` in addition to the component-specific filename.

All rows use deterministic ordering, finite numeric validation, explicit nulls
where a rate or centroid is undefined, canonical float serialization already
used by the renderer, atomic publication, and manifest SHA-256/byte accounting.

## Error handling

Fail closed before publishing if any of the following occurs:

- Component 0 does not reproduce exactly 24 exceedances out of 409 assigned
  samples;
- the prior run directory or manifest differs before and after extension
  publication;
- the extension schema version or deterministic run ID collides with the prior
  run;
- feature contributions do not sum to the stored sample distance;
- a retained feature is missing from or inconsistent with the registry;
- the canonical registry hash changes within one run;
- offset selections overlap incorrectly or do not reconstruct the full ordered
  index set for each spacing;
- a fixed half assignment cannot be mapped through the existing Hungarian
  result;
- empirical feature contributions do not reproduce squared centroid distance;
- OOD offset numerators or denominators do not reconcile with stored rows;
- any forbidden fitting, rematching, gate, model-artifact, or strategy input is
  required by the decomposition contract.

No partial success artifact is published after a validation failure.

## Testing and verification

Unit tests use adversarial small fixtures and cover:

- feature sum, ratio, mean, median, top-1, and top-5 calculations;
- registry-order tie-breaking;
- all three fixed thresholds immediately below, exactly at, and above their
  boundaries;
- strict registry family membership and explicit exclusion of range and volume
  features from volatility;
- canonical registry hash stability;
- offset selection for every 3-day and 7-day offset;
- reuse of existing assignments and matches;
- primary-coordinate empirical centroid and feature-distance arithmetic;
- identical arithmetic for `full_sample_empirical_centroid_distance` and
  `offset_empirical_centroid_distance`;
- zero-sample and one-sample groups;
- component OOD numerator, denominator, rate, and deterministic tie-breaking;
- ordered top-five and set-only agreement flags;
- immutability and diagnostic-only flags.

Isolation tests monkeypatch all fitting, rematching, gate-evaluation, model
artifact, and strategy entry points to raise if called. Renderer tests verify
new CSV schemas, JSON sections, Markdown claims, deterministic ordering, atomic
publication, manifest membership, and repeat-run byte identity.

Final verification independently recomputes from published CSV/JSON rows:

- Component 0's 24/409 population;
- every feature and family aggregate;
- the three concentration flags;
- every offset sample accounting, empirical maximum drift, maximum OOD
  component, and top-five comparison;
- every report claim and output hash.

Verification also hashes the complete prior run directory before and after the
extension command and requires byte-for-byte immutability. Two clean extension
runs must resolve to the same new run ID and produce byte-identical new output
trees.

The existing frozen K4 diagnosis test suite must remain green. The completed
diagnosis is accepted only when the full targeted and regression suites pass and
two clean executions produce byte-identical output trees.
