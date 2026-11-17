"""LP min/max load bounds of the train-level OD model with HARD two-sided hourly marginal bounds.
Diagnostic only. Peak cases are used only to ask whether the actual value lies inside the data-implied interval.
Declared in advance: eps in {0, 2%, 5%} of each eligible cell; cells with no eligible train event are slack (excluded);
no capacity cap; targets = 19 matched peak train-stops + 200 seeded random train-stops of the 6 evaluation days."""
import argparse, json, sys, time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import numpy as np, pandas as pd, scipy.sparse as sp
from scipy.optimize import linprog
sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_ground_truth as gt
import gt_arrival_curve as ac
import gt_train_od as od
from experiment_queue_model import CASES

OUT = gt.ROOT / "outputs/diagnostics/train_od"
EPS = (0.0, 0.02, 0.05)
N_SAMPLE, SEED = 200, 20261117


def constraints(P, eps):
    eb, ea = P["elig_b"] > 0, P["elig_a"] > 0
    rows = sp.vstack([P["Mb"][eb], P["Ma"][ea]], format="csr")
    obs = np.concatenate([P["B"][eb], P["A"][ea]])
    return rows, obs * (1 - eps), obs * (1 + eps)


def solve(P, c, eps, sense=1):
    rows, lo, hi = constraints(P, eps)
    if eps == 0:
        r = linprog(sense * c, A_eq=rows, b_eq=lo, bounds=(0, None), method="highs")
    else:
        r = linprog(sense * c, A_ub=sp.vstack([rows, -rows], format="csr"), b_ub=np.concatenate([hi, -lo]), bounds=(0, None), method="highs")
    return r


def load_vec(P, event):
    k = np.searchsorted([s for s, _ in P["slices"]], event, side="right") - 1
    m = (P["pk"] == k) & (P["pa"] <= event) & (P["pb"] > event)
    c = np.zeros(P["V"]); c[m] = 1
    return c


def day_job(args):
    date, eps, targets = args           # targets: list of (tag, train_id, station)
    P = od.build_problem(date); ev = P["ev"]; out = []
    feas = solve(P, np.zeros(P["V"]), eps)
    rec = dict(date=date, eps=eps, feasible=bool(feas.status == 0), status=int(feas.status))
    if feas.status == 0:
        for tag, tid, st in targets:
            e = ev.index[(ev.train_id == tid) & (ev.station == st)]
            e = int(e[0]); c = load_vec(P, e)
            lo, hi = solve(P, c, eps, 1), solve(P, c, eps, -1)
            out.append(dict(date=date, eps=eps, tag=tag, train_id=tid, station=st, hour=int(ev.hour[e]), station_idx=int(ev.station_idx[e]),
                            lp_min=float(lo.fun) if lo.status == 0 else np.nan, lp_max=float(-hi.fun) if hi.status == 0 else np.nan))
    return rec, out


def min_feasible_eps(date):
    P = od.build_problem(date); lo, hi = 0.0, 0.5
    for _ in range(9):
        mid = (lo + hi) / 2
        if solve(P, np.zeros(P["V"]), mid).status == 0: hi = mid
        else: lo = mid
    return dict(date=date, min_feasible_eps_approx=hi,
                eligible_B=float(P["B"][P["elig_b"] > 0].sum()), eligible_A=float(P["A"][P["elig_a"] > 0].sum()),
                slack_B=float(P["B"][P["elig_b"] == 0].sum()), slack_A=float(P["A"][P["elig_a"] == 0].sum()),
                cells_B_nocell=int(((P["elig_b"] == 0) & (P["B"] > 0)).sum()), cells_A_nocell=int(((P["elig_a"] == 0) & (P["A"] > 0)).sum()))


def main():
    t0 = time.perf_counter()
    comp = pd.read_csv(gt.ROOT / "outputs/peak_case_comparison.csv", encoding="utf-8-sig")
    comp = comp[comp.status == "matched"]
    targets = {}
    for _, c in comp.iterrows():
        targets.setdefault(c.service_date, []).append(("peak", c.synthetic_train_id, c.peak_station))
    rng = np.random.default_rng(SEED)
    pool = []
    for d in CASES:
        ev = od.build_problem(d)["ev"]
        for i in ev.index[ev.is_destination == 0]:
            pool.append((d, ev.train_id[i], ev.station[i]))
    pick = rng.choice(len(pool), N_SAMPLE, replace=False)
    for i in pick:
        d, tid, st = pool[i]; targets.setdefault(d, []).append(("sample", tid, st))
    jobs = [(d, e, t) for d, t in targets.items() for e in EPS]
    feas_rows, res = [], []
    with ProcessPoolExecutor(12) as ex:
        for rec, out in ex.map(day_job, jobs):
            feas_rows.append(rec); res += out
            print(json.dumps(rec), flush=True)
        mf = list(ex.map(min_feasible_eps, sorted(targets)))
    pd.DataFrame(res).to_csv(OUT / "lp_bounds.csv", index=False, encoding="utf-8-sig")
    json.dump(dict(feasibility=feas_rows, min_feasible_eps=mf, seed=SEED, eps=EPS, n_sample=N_SAMPLE,
                   seconds=time.perf_counter() - t0), open(OUT / "lp_feasibility.json", "w"), indent=1)


if __name__ == "__main__":
    main()
