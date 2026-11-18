# Graph-model check (2019-01-08 only)
graph: 81 nodes, 85 undirected edges; fit a=3.79 min, b=2.34 min/hop (hops 1-32, same-line trips n=740,839)

| group | n | within +-5 min | claimed in brief | W (min) |
|---|---|---|---|---|
| same_line_all (W=0) | 740,839 | 0.809 | 0.854 | 0.0 |
| cross_BC (both directions pooled, W=median) | 199,855 | 0.763 | 0.782 | 6.08 |
| cross_AC (both directions pooled, W=median) | 68,030 | 0.783 | 0.795 | 3.54 |
| cross_AB (both directions pooled, W=median) | 128,509 | 0.845 | 0.852 | 2.47 |

Same-line W=0 means residual vs a+b*hops without a constant; the W=median row is shown in the csv.
Residual by B-group x C-group for B<->C trips and the stage-1 hub comparison: see graph_model_check.csv rows 'BC residual ...' and 'direct_hub...'.