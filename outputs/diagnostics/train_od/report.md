# Train-level OD model (phase B; experiment/diagnostic only; config.json holds frozen arms and hashes)
Files: results.csv, summary_normal5.csv, summary_midnight_day.csv, peak_posthoc.csv/.json, lp_bounds.csv, lp_feasibility.json.
Key points
- OD arms satisfy conservation, terminal=0, load>=0 exactly; misfit to hourly marginals 0.6% (lam 0.01) to 2.4-2.8% (lam 0.1) of total observed counts; baseline has ~0 marginal misfit but 2.8% physical violation (terminal+negative). Combined TNV: baseline 0.0277 vs OD uniform 0.0060 (lam .01). The OD gain is partly tolerance: misfit is where the error goes.
- Level: OD uniform/headway arms keep loads near baseline (median 125 vs 131, 8h/18h 170 vs 158); gravity arms lower loads (decay shortens trips). Peak est/actual: baseline 0.51, OD uniform 0.62, OD headway 0.62, gravity 0.37-0.54. Still far from 1.0.
- LP bounds are vacuous: peak train-stops [0, ~5,500-7,600]; 19/19 actuals inside trivially. Hard equality infeasible on every day; feasible from about 0.2-0.4% tolerance.
