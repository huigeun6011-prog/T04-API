"""Mass-preserving smooth arrival-rate curves for the headway boarding allocation (experiment only).

Per station and service day, hourly gate counts B_i(h), h = 5..24 (24 = next-day 00h), become a
nonnegative intensity lambda_i on a 1-minute grid over 05:00..25:00 whose sum inside each hour equals
B_i(h) EXACTLY (pycnophylactic / temporal disaggregation):
    min_lambda  sum_t (D lambda)_t^2     s.t.  C lambda = B,  lambda >= 0
with D = first difference ('d1') or second difference ('d2'). No penalty outside the 05:00-25:00 window
(free ends). Hours with B=0 are exactly zero. Nonnegativity: primal active-set with sparse KKT solves.
A train's boarding window integral = integral of lambda over (previous same-direction departure,
departure]; first train of the day uses 05:00 as window start. Direction split p and the "both/only
direction still running" logic are copied from gt_assumptions.boarding_exposures, but the flat per-hour
rate is replaced by the curve mass (flat curve reproduces the existing headway exactly).
Alighting, p/q parameterisation, losses, Adam, seeds: identical to the baseline solver.
Peak cases are never read here.
"""
import json
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import scipy.sparse as sp
from scipy.sparse.linalg import spsolve
import torch
import generate_ground_truth as gt

NS, NH = gt.N_STATIONS, gt.N_HOURS
T0, NMIN = 300, 1200          # grid: minute-of-service-day 300 (05:00) .. 1500 (25:00)


def _ops(order):
    n = NMIN
    D = sp.diags([-np.ones(n - 1), np.ones(n - 1)], [0, 1], shape=(n - 1, n)) if order == 1 else \
        sp.diags([np.ones(n - 2), -2 * np.ones(n - 2), np.ones(n - 2)], [0, 1, 2], shape=(n - 2, n))
    C = sp.lil_matrix((NH, n))
    for h in range(NH):
        C[h, h * 60:(h + 1) * 60] = 1
    return (D.T @ D).tocsc(), C.tocsr()


_OPS = {}


def curve_one(b, order, max_iter=60):
    """b: 20 hourly totals -> per-minute mass (NMIN,), nonnegative, hour sums = b exactly."""
    if order not in _OPS:
        _OPS[order] = _ops(order)
    Q, C = _OPS[order]
    zero = np.zeros(NMIN, bool)
    for h in range(NH):
        if b[h] <= 0:
            zero[h * 60:(h + 1) * 60] = True
    x = np.repeat(b / 60.0, 60)
    act_hours = np.where(b > 0)[0]
    if len(act_hours) == 0:
        return np.zeros(NMIN)
    Ch = C[act_hours]
    bh = b[act_hours]
    for _ in range(max_iter):
        free = np.where(~zero)[0]
        Qf = Q[free][:, free] + 1e-9 * sp.eye(len(free))
        Cf = Ch[:, free]
        K = sp.bmat([[2 * Qf, Cf.T], [Cf, None]], format="csc")
        sol = spsolve(K, np.concatenate([np.zeros(len(free)), bh]))
        xf, nu = sol[:len(free)], sol[len(free):]
        # primal step from feasible x toward xf
        xt = np.zeros(NMIN); xt[free] = xf
        d = xt - x
        neg = (xt < -1e-10) & (~zero)
        if neg.any():
            ratio = np.where(d < 0, -x / np.where(d < 0, d, -1), np.inf)
            ratio = np.where(neg, ratio, np.inf)
            a = min(1.0, ratio.min())
            x = x + a * d
            x = np.where(np.abs(x) < 1e-10, 0, x)
            zero = zero | (neg & (ratio <= a + 1e-12))
            continue
        x = xt
        # release zero cells with negative multiplier (mu = grad - C' nu)
        grad = 2 * (Q @ x)
        mu = grad - Ch.T @ nu
        cand = zero & (~np.isin(np.arange(NMIN), np.where(np.repeat(b <= 0, 60))[0])) & (mu < -1e-8)
        if not cand.any():
            break
        zero[np.argmin(np.where(cand, mu, 0))] = False
    x = np.maximum(x, 0)
    for h in range(NH):   # exact hour mass (removes tolerance dust)
        s = x[h * 60:(h + 1) * 60].sum()
        if b[h] > 0 and s > 0:
            x[h * 60:(h + 1) * 60] *= b[h] / s
    return x


def build_curves(B_obs, mode, mix=1.0):
    """B_obs (NS,NH) -> cumulative mass (NS, NMIN+1). mode 'flat' | 'd1' | 'd2'."""
    cum = np.zeros((NS, NMIN + 1))
    for s in range(NS):
        flat = np.repeat(B_obs[s].astype(float) / 60.0, 60)
        lam = flat if mode == "flat" else mix * curve_one(B_obs[s].astype(float), 1 if mode == "d1" else 2) + (1 - mix) * flat
        cum[s, 1:] = np.cumsum(lam)
    return cum


def curve_edges(stops, cum):
    """Like gt_assumptions.boarding_exposures, but window masses come from the cumulative curve."""
    groups = {}
    for index, stop in enumerate(stops):
        if stop["is_destination"]:
            continue
        hour, minute = map(int, stop["time"].split(":"))
        if hour == 0:
            hour = 24
        groups.setdefault((stop["station_idx"], stop["dir_code"]), {}).setdefault(hour * 60 + minute, []).append(index)
    final = {k: max(v) for k, v in groups.items()}
    hours = gt.HOURS
    coverage = np.zeros((NS, NH), np.float32); both_cov = np.zeros_like(coverage)
    for s in range(NS):
        up_end, dn_end = final.get((s, 0), 300), final.get((s, 1), 300)
        for hi, hour in enumerate(hours):
            coverage[s, hi] = max(0, min((hour + 1) * 60, max(up_end, dn_end)) - hour * 60) / 60
            both_cov[s, hi] = max(0, min((hour + 1) * 60, min(up_end, dn_end)) - hour * 60) / 60

    def mass(s, l, r):
        l, r = min(max(l, T0), T0 + NMIN), min(max(r, T0), T0 + NMIN)
        return cum[s, r - T0] - cum[s, l - T0]
    edges = []
    for (s, d), deps in groups.items():
        prev = 300
        other_end = final.get((s, 1 - d), 300)
        for dep, idxs in sorted(deps.items()):
            for hi, hour in enumerate(hours):
                l, r = max(prev, hour * 60), min(dep, (hour + 1) * 60)
                if r <= l:
                    continue
                m = min(r, max(l, other_end))   # end of the "both directions running" part
                mb, mo = mass(s, l, m), mass(s, m, r)
                for i in idxs:
                    edges.append((i, s, hi, d, mb / len(idxs), mo / len(idxs)))
            prev = dep
    return edges, coverage, both_cov


def load_day(date_str):
    nxt = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    curr = json.loads((gt.SUBWAY_DIR / f"{date_str}.json").read_text(encoding="utf-8"))
    p2 = gt.SUBWAY_DIR / f"{nxt}.json"
    nd = json.loads(p2.read_text(encoding="utf-8")) if p2.exists() else None
    B = np.zeros((NS, NH), np.float32); A = np.zeros((NS, NH), np.float32)
    for sid_str, st in curr["stations"].items():
        sid = int(sid_str)
        if not 101 <= sid <= 122:
            continue
        for h, c in st.get("boardings", {}).items():
            if 5 <= int(h) <= 23: B[sid - 101, gt.HOUR_TO_IDX[int(h)]] += c
        for h, c in st.get("alightings", {}).items():
            if 5 <= int(h) <= 23: A[sid - 101, gt.HOUR_TO_IDX[int(h)]] += c
    if nd is not None:
        for sid_str, st in nd["stations"].items():
            sid = int(sid_str)
            if 101 <= sid <= 122:
                B[sid - 101, gt.HOUR_TO_IDX[24]] += st.get("boardings", {}).get("0", 0)
                A[sid - 101, gt.HOUR_TO_IDX[24]] += st.get("alightings", {}).get("0", 0)
    return B, A


def solve_day(date_str, mode="baseline", mix=1.0, epochs=1000, init_seed=None, diagnostics=None, fixed_pq=None):
    """mode: 'baseline' (even split) | 'flat' (== existing headway) | 'd1' | 'd2' (curve; mix with flat)."""
    torch.set_num_threads(1)
    B_obs, A_obs = load_day(date_str)
    trains = gt.get_subway_trains(date_str, gt.get_day_type(date_str))
    n_ub, n_ua, n_db, n_da = (np.zeros((NS, NH), np.float32) for _ in range(4))
    meta, slices = [], []
    for t in trains:
        d = 0 if t["direction"] == "상행" else 1
        n = len(t["stops"]); start = len(meta)
        for i, st in enumerate(t["stops"]):
            s_idx = gt.STATION_TO_IDX[st["station"]]
            hh = gt.normalize_hour(int(st["time"].split(":")[0])); h_idx = gt.HOUR_TO_IDX[hh]
            org, dest = i == 0, i == n - 1
            meta.append(dict(train_id=t["train_id"], direction=t["direction"], dir_code=d, station=st["station"],
                             station_idx=s_idx, time=st["time"], hour=hh, hour_idx=h_idx,
                             is_origin=int(org), is_destination=int(dest)))
            (n_ub if d == 0 else n_db)[s_idx, h_idx] += 0 if dest else 1
            (n_ua if d == 0 else n_da)[s_idx, h_idx] += 0 if org else 1
        slices.append((start, len(meta), d))
    N = len(meta)
    T = lambda x, **k: torch.tensor(x, **k)
    B_t, A_t = T(B_obs), T(A_obs)
    nub, nua, ndb, nda = T(n_ub), T(n_ua), T(n_db), T(n_da)
    idx_s = T([m["station_idx"] for m in meta], dtype=torch.long); idx_h = T([m["hour_idx"] for m in meta], dtype=torch.long)
    t_dir = T([float(m["dir_code"]) for m in meta])
    m_dest = T([float(m["is_destination"]) for m in meta]); m_orig = T([float(m["is_origin"]) for m in meta])

    headway = mode != "baseline"
    coverage = both_cov = None
    if headway:
        cum = build_curves(B_obs, "flat" if mode == "flat" else mode, mix)
        edges, coverage, both_cov = curve_edges(meta, cum)
        E = np.asarray(edges, np.float64)
        e_stop, e_st, e_h = (T(E[:, k], dtype=torch.long) for k in (0, 1, 2))
        e_dir, e_mb, e_mo = (T(E[:, k], dtype=torch.float32) for k in (3, 4, 5))

    pp = np.clip(np.array([[s / (NS - 1)] * NH for s in range(NS)], np.float32), .01, .99)
    qp = np.clip(1 - np.array([[s / (NS - 1)] * NH for s in range(NS)], np.float32), .01, .99)
    pl0 = np.log(pp[1:-1] / (1 - pp[1:-1])); ql0 = np.log(qp[1:-1] / (1 - qp[1:-1]))
    if init_seed is not None:
        rng = np.random.default_rng(init_seed)
        pl0 += rng.normal(0, .25, pl0.shape).astype(np.float32); ql0 += rng.normal(0, .25, ql0.shape).astype(np.float32)
    p_logits = torch.nn.Parameter(T(pl0)); q_logits = torch.nn.Parameter(T(ql0))
    prior_p, prior_q = T(pp[1:-1]), T(qp[1:-1])
    opt = torch.optim.Adam([p_logits, q_logits], lr=0.1)
    p_ident = T(both_cov > 0)[1:-1] if headway else ((nub > 0) & (ndb > 0))[1:-1]
    q_ident = ((nua > 0) & (nda > 0))[1:-1]
    lengths = T([e - s for s, e, _ in slices]); offs = torch.arange(int(lengths.max()))[None, :]
    starts = T([s for s, _, _ in slices])[:, None]
    valid = offs < lengths[:, None]; gidx = (starts + offs).clamp(max=N - 1)

    def full_pq():
        z, o = torch.zeros((1, NH)), torch.ones((1, NH))
        return torch.cat([z, torch.sigmoid(p_logits), o]), torch.cat([o, torch.sigmoid(q_logits), z])

    def stops(p, q):
        pu, pd_ = gt.feasible_shares(p, nub, ndb); qu, qd = gt.feasible_shares(q, nua, nda)
        a_up, a_dn = qu * A_t / nua.clamp(min=1), qd * A_t / nda.clamp(min=1)
        a = ((1 - t_dir) * a_up[idx_s, idx_h] + t_dir * a_dn[idx_s, idx_h]) * (1 - m_orig)
        if headway:
            up = p[e_st, e_h]
            share = (1 - e_dir) * up + e_dir * (1 - up)
            b = torch.zeros(N).scatter_add(0, e_stop, share * e_mb + e_mo)
        else:
            b_up, b_dn = pu * B_t / nub.clamp(min=1), pd_ * B_t / ndb.clamp(min=1)
            b = ((1 - t_dir) * b_up[idx_s, idx_h] + t_dir * b_dn[idx_s, idx_h]) * (1 - m_dest)
        return b, a

    def prior_loss():
        d1 = (torch.sigmoid(p_logits) - prior_p) ** 2; d2 = (torch.sigmoid(q_logits) - prior_q) ** 2
        return d1.mul(p_ident).sum() / p_ident.sum().clamp(min=1) + d2.mul(q_ident).sum() / q_ident.sum().clamp(min=1)

    best, best_ep, best_par = float("inf"), 0, None
    if fixed_pq is None:
        for ep in range(epochs):
            opt.zero_grad()
            p, q = full_pq(); b, a = stops(p, q)
            load = torch.cumsum((b - a)[gidx] * valid, dim=1)
            term = load.gather(1, (lengths - 1)[:, None]).squeeze(1)
            loss = torch.mean(term ** 2) + torch.mean(torch.relu(-load[valid]) ** 2) + 2.0 * prior_loss()
            v = float(loss.detach())
            if v < best:
                best, best_ep, best_par = v, ep + 1, (p_logits.detach().clone(), q_logits.detach().clone())
            loss.backward(); opt.step()
        with torch.no_grad():
            p_logits.copy_(best_par[0]); q_logits.copy_(best_par[1])
            p, q = full_pq(); b, a = stops(p, q)
    else:
        with torch.no_grad():
            p, q = T(fixed_pq[0]), T(fixed_pq[1]); b, a = stops(p, q)
    b, a = b.detach().numpy().astype(np.float64), a.detach().numpy().astype(np.float64)
    frame = pd.DataFrame(meta)
    frame["board"], frame["alight"] = b, a
    frame["raw_load"] = np.concatenate([np.cumsum(b[s:e] - a[s:e]) for s, e, _ in slices])
    frame["load"] = np.maximum(frame.raw_load, 0)
    if diagnostics is not None:
        diagnostics.update(date=date_str, mode=mode, mix=mix, best_epoch=best_ep, best_loss=best,
                           board_observed_total=float(B_obs.sum()), alight_observed_total=float(A_obs.sum()),
                           board_allocated_total=float(b.sum()), alight_allocated_total=float(a.sum()),
                           board_slack_after_last_departure=float((B_obs * (1 - coverage)).sum()) if headway else None)
    return frame, dict(p_fit=p.detach().numpy(), q_fit=q.detach().numpy(), B=B_obs, A=A_obs,
                       cum=(cum if headway else None))
