"""Line C Stage 1: fixed-hub check on 2019-01-08 (no other day).
GATE (declared in docs/AI/HANGZHOU_TIMETABLE_BRIEF.md section 7): B-C within-5-min share >= 60% AND >= B0 single-hub share (0.5986) - 3pp;
A-C within-5-min share >= 80%.  Model: minutes = c_X(d_X) + c_C(d_C) + W, W = median residual per hub (fitted).  Failure => STOP.md."""
import json, sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import numpy as np, pandas as pd
from lineC_common import *

tr = pd.read_pickle(CACHE / "trips_2019-01-08.pkl")
res = {}


def evaluate(X, hub_x_id, hub_c_id, branch=True, label=""):
    a = tr[(tr.entry_line == X) & (tr.exit_line == "C")]; b = tr[(tr.entry_line == "C") & (tr.exit_line == X)]
    xs = np.concatenate([a.entry_st.to_numpy(), b.exit_st.to_numpy()]); cs = np.concatenate([a.exit_st.to_numpy(), b.entry_st.to_numpy()]); m = np.concatenate([a.minutes.to_numpy(), b.minutes.to_numpy()])
    dx = b_dist(xs, np.full(len(xs), hub_x_id), branch) if X == "B" else np.abs(np.array([POS["A"][s] for s in xs]) - POS["A"][hub_x_id])
    dc = np.abs(np.array([POS["C"][s] for s in cs]) - POS["C"][hub_c_id])
    r = m - cfun(X, dx) - cfun("C", dc); W = float(np.median(r)); ar = np.abs(r - W)
    return dict(label=label, n=len(m), W=round(W, 2), within5=round(float((ar <= 5).mean()), 4), mean_abs=round(float(ar.mean()), 3), median_abs=round(float(np.median(ar)), 3))


rows = [dict(pair="BC", **evaluate("B", 10, 51, True, "fixed B10-C51 (branch-aware B distances)")),
        dict(pair="BC", **evaluate("B", 10, 51, False, "fixed B10-C51 (plain ID-order B)")),
        dict(pair="BC", **evaluate("B", 10, 48, True, "B0 data-driven B10-C48 (branch-aware)")),
        dict(pair="BC", **evaluate("B", 10, 48, False, "B0 data-driven B10-C48 (plain, as in B0)")),
        dict(pair="AC", **evaluate("A", 77, 46, True, "fixed A77-C46"))]
df = pd.DataFrame(rows); df.to_csv(OUT / "stage1_fixed_hubs.csv", index=False); print(df.to_string())
bc = df[df.label.str.startswith("fixed B10-C51 (branch")].iloc[0]; b0 = 0.5986; ac = df[df.pair == "AC"].iloc[0]
plain = df[df.label.str.startswith("fixed B10-C51 (plain")].iloc[0]
ok_bc = (bc.within5 >= 0.60) and (bc.within5 >= b0 - 0.03); ok_ac = ac.within5 >= 0.80
res = dict(bc_within5_branch=bc.within5, bc_within5_plain=plain.within5, ac_within5=ac.within5, gate_bc=bool(ok_bc), gate_ac=bool(ok_ac), passed=bool(ok_bc and ok_ac))
(OUT / "stage1_result.json").write_text(json.dumps(res, indent=1), encoding="utf-8"); print(res)
if not res["passed"]:
    (OUT / "STOP.md").write_text(f"# STOP at Stage 1 (fixed hub check)\n\n{json.dumps(res)}\n\nSee stage1_fixed_hubs.csv. Gate: B-C within-5 >= 60% (and >= B0 0.5986 - 3pp), A-C >= 80%.\n", encoding="utf-8")
