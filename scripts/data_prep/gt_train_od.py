"""Train-level OD estimate: x[k,a,b] >= 0 riders of train k boarding at its stop a and alighting at later stop b.
Conservation, terminal 0 and load >= 0 hold exactly by construction (load after stop i = sum_{a<=i<b} x[k,a,b]).
Observed hourly per-station boardings B(s,h) / alightings A(s,h) (both directions together, h = hour of the
train's stop time, 24 = next-day 00h) enter as SOFT marginals; cells with no eligible train event are explicit slack.

  min_x  sum_cells (fit - obs)^2 / (obs + 10)  +  lam * sum_v ( x log(x/q) - x + q )          x >= 0
Solved with L-BFGS-B on x (sparse gradients). Base q is built so that each boarding cell's mass equals B(s,h),
split over the events of that cell by a train weight, and over later stops by an OD weight g(a,b).
Experiment/diagnostic only. Peak cases are never read here.
"""
import numpy as np
import pandas as pd
import scipy.sparse as sp
from scipy.optimize import minimize
import generate_ground_truth as gt
import gt_arrival_curve as ac

NS, NH = gt.N_STATIONS, gt.N_HOURS
NC = NS * NH


def build_problem(date_str):
    B, A = ac.load_day(date_str)
    trains = gt.get_subway_trains(date_str, gt.get_day_type(date_str))
    meta, slices = [], []
    for t in trains:
        d = 0 if t["direction"] == "상행" else 1
        n = len(t["stops"]); start = len(meta)
        for i, st in enumerate(t["stops"]):
            s_idx = gt.STATION_TO_IDX[st["station"]]
            hh = gt.normalize_hour(int(st["time"].split(":")[0])); h_idx = gt.HOUR_TO_IDX[hh]
            hm = st["time"].split(":"); mnt = int(hm[0]) * 60 + int(hm[1])
            meta.append(dict(train_id=t["train_id"], direction=t["direction"], dir_code=d, station=st["station"],
                             station_idx=s_idx, time=st["time"], hour=hh, hour_idx=h_idx, minute=mnt,
                             is_origin=int(i == 0), is_destination=int(i == n - 1), pos=i))
        slices.append((start, len(meta)))
    ev = pd.DataFrame(meta)
    N = len(ev)
    cell = (ev.station_idx * NH + ev.hour_idx).to_numpy()
    # pair variables
    pk, pa, pb = [], [], []
    for k, (s, e) in enumerate(slices):
        n = e - s
        a_idx, b_idx = np.triu_indices(n, 1)
        pk.append(np.full(len(a_idx), k)); pa.append(s + a_idx); pb.append(s + b_idx)
    pk, pa, pb = (np.concatenate(v) for v in (pk, pa, pb))
    V = len(pa)
    Mb = sp.csr_matrix((np.ones(V), (cell[pa], np.arange(V))), shape=(NC, V))
    Ma = sp.csr_matrix((np.ones(V), (cell[pb], np.arange(V))), shape=(NC, V))
    elig_b = np.bincount(cell[(ev.is_destination == 0).to_numpy()], minlength=NC)
    elig_a = np.bincount(cell[(ev.is_origin == 0).to_numpy()], minlength=NC)
    return dict(date=date_str, B=B.reshape(-1).astype(float), A=A.reshape(-1).astype(float), ev=ev, slices=slices,
                pk=pk, pa=pa, pb=pb, V=V, N=N, cell=cell, Mb=Mb, Ma=Ma, elig_b=elig_b, elig_a=elig_a)


def event_weights(P, kind):
    ev = P["ev"]
    if kind == "uniform":
        return np.ones(P["N"])
    # headway: gap (minutes) since the previous same-direction departure at that station (05:00 for the first)
    w = np.zeros(P["N"])
    for (s, d), g in ev[ev.is_destination == 0].groupby(["station_idx", "dir_code"]):
        g = g.sort_values(["minute"])
        prev = 300
        for minute, grp in g.groupby("minute"):
            gap = max(minute - prev, 1)
            w[grp.index.to_numpy()] = gap / len(grp)
            prev = minute
    return w


def base_q(P, train_weight="uniform", beta=None, gamma=1.0):
    """q[v]: boarding-cell mass B(s,h) split by train weight, then over later stops by exp(-beta*d)*(gamma if d==1)."""
    ev, cell = P["ev"], P["cell"]
    w = event_weights(P, train_weight) * (ev.is_destination == 0).to_numpy()
    tot = np.bincount(cell, weights=w, minlength=NC)
    m = np.where(tot[cell] > 0, P["B"][cell] * w / np.maximum(tot[cell], 1e-12), 0.0)       # mass per event
    d = (P["pb"] - P["pa"]).astype(float)
    g = np.ones(P["V"]) if beta is None else np.exp(-beta * d) * np.where(d == 1, gamma, 1.0)
    gs = np.bincount(P["pa"], weights=g, minlength=P["N"])
    return m[P["pa"]] * g / np.maximum(gs[P["pa"]], 1e-12)


def fit(P, q, lam, maxiter=20000):
    mask = q > 0
    qv = q[mask]
    Mb, Ma = P["Mb"][:, mask], P["Ma"][:, mask]
    ob, oa = P["B"], P["A"]
    wb = (P["elig_b"] > 0) / (ob + 10.0)
    wa = (P["elig_a"] > 0) / (oa + 10.0)

    def fun(v):
        rb, ra = Mb @ v - ob, Ma @ v - oa
        val = (wb * rb ** 2).sum() + (wa * ra ** 2).sum() + lam * (v * np.log(v / qv) - v + qv).sum()
        g = 2 * (Mb.T @ (wb * rb)) + 2 * (Ma.T @ (wa * ra)) + lam * np.log(v / qv)
        return val, g
    res = minimize(fun, qv.copy(), jac=True, method="L-BFGS-B", bounds=[(1e-12, None)] * len(qv),
                   options=dict(maxiter=maxiter, maxfun=maxiter * 2, ftol=1e-13, gtol=1e-8, maxcor=30))
    x = np.zeros(P["V"]); x[mask] = res.x
    pg = np.abs(res.jac[(res.x > 1e-10) | (res.jac < 0)]).max() if len(res.jac) else 0.0
    return x, dict(nit=int(res.nit), converged=bool(res.success), message=str(res.message), objective=float(res.fun),
                   proj_grad_inf=float(pg))


def to_frame(P, x):
    ev = P["ev"].copy()
    N = P["N"]
    ev["board"] = np.bincount(P["pa"], weights=x, minlength=N)
    ev["alight"] = np.bincount(P["pb"], weights=x, minlength=N)
    ev["raw_load"] = np.concatenate([np.cumsum(ev.board.to_numpy()[s:e] - ev.alight.to_numpy()[s:e]) for s, e in P["slices"]])
    ev["load"] = np.maximum(ev.raw_load, 0)
    return ev


def marginal_stats(P, frame):
    fb = np.bincount(P["cell"], weights=frame.board.to_numpy(), minlength=NC)
    fa = np.bincount(P["cell"], weights=frame.alight.to_numpy(), minlength=NC)
    out = {}
    for name, fit_, obs, elig in (("B", fb, P["B"], P["elig_b"]), ("A", fa, P["A"], P["elig_a"])):
        e = elig > 0
        out[f"{name}_rmse_eligible"] = float(np.sqrt(np.mean((fit_[e] - obs[e]) ** 2)))
        out[f"{name}_rel_l1_eligible"] = float(np.abs(fit_[e] - obs[e]).sum() / max(obs[e].sum(), 1))
        out[f"{name}_slack_nocell"] = float(obs[~e].sum())
        out[f"{name}_l1_all"] = float(np.abs(fit_ - obs).sum())     # slack cells count as fully missed
        out[f"{name}_total_obs"] = float(obs.sum())
    return out


def physical_l1(frame):
    t = frame.loc[frame.is_destination == 1, "raw_load"].abs().sum()
    n = np.maximum(-frame.raw_load.to_numpy(), 0).sum()
    return float(t), float(n)
