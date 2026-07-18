# Frozen K4 Diagnosis Completion

This diagnostic-only report completes the frozen K4 cause diagnosis.

## Component 0 OOD (24/409)

- Top five features: volume_cv_3d, rv_ratio_1d_3d, volume_ratio_1d_3d, directional_efficiency_3d, max_runup_3d
- family returns: contribution_ratio=0.15852209232848474
- family volatility: contribution_ratio=0.18227287037132553
- family range: contribution_ratio=0.051577517044566208
- family path: contribution_ratio=0.097078418217952184
- family reversal: contribution_ratio=0.13576591328613255
- family excursion: contribution_ratio=0.084625147825062114
- family structure: contribution_ratio=0.1592657286691801
- family volume: contribution_ratio=0.13089231225729667
- single_feature_concentration=false
- volatility_family_concentration=false
- recurrent_feature_dominance=false

## Distinct distance metrics

- fitted_parameter_centroid_distance=2.3526219570607076
- full_sample_empirical_centroid_distance=2.2760051902315195
- offset_empirical_centroid_distance is reported for every 3-day and 7-day offset.

## Offset consistency

- 3-day offset=0 origin=2021-01-01T00:00:00Z offset_empirical_centroid_distance: max=2.2400299558656487 half=B primary_component=3 primary_fingerprint=e37692350fa4ad4230e3336e half_component=1 half_fingerprint=79a3672f5b2e02b1cc6b62e6 maximum_ood_primary_component=0 maximum_ood_fingerprint=39e3bacf11776871a5ff8111 top_five=rv_1d,volume_cv_3d,rv_3d,range_ratio_3d,max_runup_3d
- 3-day offset=1 origin=2021-01-01T00:00:00Z offset_empirical_centroid_distance: max=2.511041421190602 half=B primary_component=3 primary_fingerprint=e37692350fa4ad4230e3336e half_component=1 half_fingerprint=79a3672f5b2e02b1cc6b62e6 maximum_ood_primary_component=0 maximum_ood_fingerprint=39e3bacf11776871a5ff8111 top_five=rv_1d,rv_4h,volume_cv_3d,rv_3d,range_ratio_3d
- 3-day offset=2 origin=2021-01-01T00:00:00Z offset_empirical_centroid_distance: max=2.2381543395551282 half=B primary_component=3 primary_fingerprint=e37692350fa4ad4230e3336e half_component=1 half_fingerprint=79a3672f5b2e02b1cc6b62e6 maximum_ood_primary_component=3 maximum_ood_fingerprint=e37692350fa4ad4230e3336e top_five=volume_cv_3d,rv_3d,rv_4h,range_ratio_3d,rv_1d
- 7-day offset=0 origin=2021-01-01T00:00:00Z offset_empirical_centroid_distance: max=2.329821805691306 half=B primary_component=3 primary_fingerprint=e37692350fa4ad4230e3336e half_component=1 half_fingerprint=79a3672f5b2e02b1cc6b62e6 maximum_ood_primary_component=3 maximum_ood_fingerprint=e37692350fa4ad4230e3336e top_five=rv_1d,range_ratio_3d,return_12h,rv_3d,volume_cv_3d
- 7-day offset=1 origin=2021-01-01T00:00:00Z offset_empirical_centroid_distance: max=2.6590553575126084 half=A primary_component=3 primary_fingerprint=e37692350fa4ad4230e3336e half_component=2 half_fingerprint=5ae28957385af58ebee4cf8e maximum_ood_primary_component=2 maximum_ood_fingerprint=dddf565fe433ec33a8d07106 top_five=return_12h,return_1d,max_drawdown_3d,rv_3d,return_3d
- 7-day offset=2 origin=2021-01-01T00:00:00Z offset_empirical_centroid_distance: max=4.0058716342608269 half=B primary_component=3 primary_fingerprint=e37692350fa4ad4230e3336e half_component=1 half_fingerprint=79a3672f5b2e02b1cc6b62e6 maximum_ood_primary_component=0 maximum_ood_fingerprint=39e3bacf11776871a5ff8111 top_five=rv_1d,rv_4h,volume_ratio_1d_3d,rv_ratio_1d_3d,max_runup_3d
- 7-day offset=3 origin=2021-01-01T00:00:00Z offset_empirical_centroid_distance: max=3.2333030867511883 half=B primary_component=3 primary_fingerprint=e37692350fa4ad4230e3336e half_component=1 half_fingerprint=79a3672f5b2e02b1cc6b62e6 maximum_ood_primary_component=2 maximum_ood_fingerprint=dddf565fe433ec33a8d07106 top_five=rv_1d,volume_cv_3d,max_runup_3d,rv_3d,directional_efficiency_1d
- 7-day offset=4 origin=2021-01-01T00:00:00Z offset_empirical_centroid_distance: max=3.5594677940225892 half=B primary_component=3 primary_fingerprint=e37692350fa4ad4230e3336e half_component=1 half_fingerprint=79a3672f5b2e02b1cc6b62e6 maximum_ood_primary_component=3 maximum_ood_fingerprint=e37692350fa4ad4230e3336e top_five=volume_ratio_1d_3d,volume_cv_3d,rv_3d,max_drawdown_3d,rv_ratio_1d_3d
- 7-day offset=5 origin=2021-01-01T00:00:00Z offset_empirical_centroid_distance: max=2.4076608893203826 half=A primary_component=3 primary_fingerprint=e37692350fa4ad4230e3336e half_component=2 half_fingerprint=5ae28957385af58ebee4cf8e maximum_ood_primary_component=3 maximum_ood_fingerprint=e37692350fa4ad4230e3336e top_five=range_ratio_3d,max_drawdown_3d,rv_1d,return_2d,rv_3d
- 7-day offset=6 origin=2021-01-01T00:00:00Z offset_empirical_centroid_distance: max=2.4253243460667795 half=A primary_component=3 primary_fingerprint=e37692350fa4ad4230e3336e half_component=2 half_fingerprint=5ae28957385af58ebee4cf8e maximum_ood_primary_component=3 maximum_ood_fingerprint=e37692350fa4ad4230e3336e top_five=rv_3d,range_ratio_3d,max_drawdown_3d,rv_1d,max_runup_3d
- 3-day drift component: 3/3 (universal)
- 3-day OOD component: 2/3 (mixed)
- 3-day ordered top five: 0/3 (subset-only)
- 3-day top-five set: 2/3 (mixed)
- 7-day drift component: 7/7 (universal)
- 7-day OOD component: 1/7 (mixed)
- 7-day ordered top five: 0/7 (subset-only)
- 7-day top-five set: 0/7 (subset-only)

No model gate was re-evaluated and no strategy mapping was performed.
