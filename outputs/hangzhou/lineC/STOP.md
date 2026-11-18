# STOP at Stage 1 (fixed-hub check), 2019-01-08 only
Gate (declared in docs/AI/HANGZHOU_TIMETABLE_BRIEF.md section 7 before the run): B-C within-5-min >= 60% and not worse than B0's 59.9% by more than 3 points; A-C within-5-min >= 80%.

## Numbers (stage1_fixed_hubs.csv)
| route | hub | W (min) | within +-5 min | mean abs res | median abs res |
|---|---|---|---|---|---|
| A-C (68,030 trips) | A77-C46 | 7.16 | **88.4%** | 2.81 | 2.06 | passes (>= 80%)
| B-C (199,855 trips) | B10-C51, branch-aware B distances | 8.97 | **57.8%** | 6.72 | 3.87 | FAILS (< 60%)
| B-C | B10-C51, plain ID-order B | 8.70 | 59.1% | 6.52 | 3.73 | also < 60%
| B-C | B0 data-driven B10-C48, branch-aware | 4.50 | 56.0% | 5.91 | 4.33 |
| B-C | B0 data-driven B10-C48, plain (as in B0) | 4.02 | 59.8% | 5.48 | 3.95 |
C51 does NOT explain B-C better than C48: mean |residual| 6.7 vs 5.9 (branch-aware) and 6.5 vs 5.5 (plain); within-5 differs only by 2 points in C51's favour (branch-aware) or 0.7 points against it (plain). A scan over B hub in {9,10,11} and C hub in 46..52 (stage1_diag_hub_scan.csv) puts the lowest mean |res| at B10 with C49/C48; no hub reaches 60% within 5 min either.

## Diagnosis (stage1_diag_by_side.csv, stage1_diag_by_hour.csv; diagnosis only, no gate or setting changed)
- The one-hub model fits one geometric quadrant well and the others badly. Within +-5 min: B<10 with C above the hub 86.6% (median residual +1.1 min); B>=10 trunk with C above 67.1% (+2.3); B<10 with C below 51.3% (-2.7); **B>=10 trunk with C below the hub only 33.4% (median -9.1 min, i.e. trips are 9 minutes faster than the hub route implies)**; branch ids 28-33 with C above 9.4% (median +13.8), with C below 35.4%.
- Residuals do not depend on time of day (within-5 55-60% in every period), so this is a structural mismatch, not a rush-hour wait effect.
- Best reading: for trips from B stations beyond the hub to C stations before the hub (positions below C51 in ID order) the real route is much shorter than going through B10 and C51. Possible causes, none verified: (1) ID order along C is not the geographic order on one side of C51 (the C ID-order hypothesis rests on same-line pairs only, Spearman 0.93-0.96), (2) there is another B-C transfer opportunity or a different geometry than the assumed single interchange, (3) the Y-branch ordering of B is wrong beyond id 20 for stations other than 28-33, (4) our same-line leg model c(d) (2.4-2.8 min per station) overstates times on part of the lines.
- A-C is not affected (88.4%), so the C-side hub C46 and the C ID order near it look consistent; the problem is specific to B-C.
Per the instruction I stop here and have not run Stage 2 or later; no 2019-01-15 data was opened.
