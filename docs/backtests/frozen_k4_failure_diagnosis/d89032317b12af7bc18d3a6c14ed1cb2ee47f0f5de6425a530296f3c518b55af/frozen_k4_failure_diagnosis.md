# Frozen K4 Failure Diagnosis

This report is diagnostic-only and cannot replace the frozen primary model.

- Replay status: `reproduced`

## 1. Were the two frozen failure values reproduced?

Yes. The centroid distance and OOD exceedance rate reproduced within tolerance.

## 2. Which matched cluster pair produced 2.3526?

B half, primary 3 -> half 1.

## 3. Which features contributed most of the distance?

rv_1d=1.0224437470232228, volume_cv_3d=0.94926586678636593, rv_4h=0.83434865130605129, rv_3d=0.78868737761330965, range_ratio_3d=0.7165471064400567

## 4. Does the shift persist beyond the mean?

coordinate_median=1.1604719190496371; mean=0.96942069656995722; medoid=3.4862741717357113; trimmed_mean_10pct=1.0184168543781285

## 5. How much does distance fall after removing tail samples?

exclude_farthest_1=0.95733089841446417; exclude_farthest_1pct=0.98211105897934059; exclude_farthest_3=0.99602130263857636; exclude_farthest_5=1.0469960440022945

## 6. Which clusters and features dominate the 4.631% OOD rate?

component 0 has 24/409 exceedances.

## 7. Do centroid drift and OOD failure hit the same cluster/features?

largest centroid drift primary component=3; largest OOD component=0; same_cluster=false.

## 8. Do covariance-aware component distances show the same anomaly?

bhattacharyya=1.0853748701477617; diagonal_wasserstein_2=7.9876905683930799; euclidean=2.3526219570607076; symmetric_kl=5.0143890687753832

## 9. Does the conclusion hold for 3-day and 7-day subsamples?

3d/0:n=547; 3d/1:n=547; 3d/2:n=547; 7d/0:n=235; 7d/1:n=235; 7d/2:n=235; 7d/3:n=234; 7d/4:n=234; 7d/5:n=234; 7d/6:n=234

## 10. How is the failure cause classified?

component-ood-concentration, covariance-aware-drift, specific-cluster-drift
