"""Data-derived direction prior (p_hat, q_hat) from per-hour boarding/alighting marginals via an
OD-flow fit, plugged into the otherwise unchanged baseline p/q optimizer (experiment only).

OD fit per service day and hour column h (5..24; 24 = next-day 00h, as in generate_ground_truth):
  variables x_ij >= 0, i != j (22x22), where B_i,A_j are observed counts scaled so the mean marginal ~ 1.
  soft : min  sum_i (sum_j x_ij - B_i)^2 + sum_j (sum_i x_ij - A_j)^2 + lam * sum x log(x/q) - x + q
  ipf  : A rescaled to sum B, then Furness iterations from q (hard marginals)
  base q_ij = f(d_ij) * B_i * A_j   (gravity; d = |i-j| stops, f = exp(-beta d) * (gamma if d == 1))
           or B_i * A_j             (uniform control, f = 1), rescaled to the marginal mass.
Direction: dir_code 0 = up = toward index 0 (판암). p_hat_i = sum_{j<i} x_ij / sum_j x_ij,
q_hat_j = sum_{i>j} x_ij / sum_i x_ij. Cells with near-zero flow fall back to the static geographic prior.
Peak cases are never read here. x is only a prior generator; the optimizer is not given x.
"""
import json
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import torch
from scipy.optimize import minimize
import generate_ground_truth as gt

NS, NH = gt.N_STATIONS, gt.N_HOURS


def static_prior():
    s = np.arange(NS, dtype=np.float32)[:, None] / (NS - 1) * np.ones((1, NH), np.float32)
    return np.clip(s, .01, .99), np.clip(1 - s, .01, .99)


def decay(beta, gamma):
    d = np.abs(np.arange(NS)[:, None] - np.arange(NS)[None, :]).astype(float)
    f = np.exp(-beta * d) * np.where(d == 1, gamma, 1.0)
    np.fill_diagonal(f, 0)
    return f


def fit_hour(B, A, cfg):
    """Return (p_hat, q_hat) arrays of length NS with NaN where undefined."""
    nan = np.full(NS, np.nan)
    if B.sum() <= 0 or A.sum() <= 0:
        return nan, nan.copy()
    s = (B.sum() + A.sum()) / (2 * NS)
    b, a = B / s, A / s
    if cfg["kind"] == "ipf":
        a = a * b.sum() / a.sum()
    f = decay(cfg["beta"], cfg["gamma"]) if cfg["base"] == "gravity" else 1 - np.eye(NS)
    q = f * b[:, None] * a[None, :]
    if q.sum() <= 0:
        return nan, nan.copy()
    q = q * ((b.sum() + a.sum()) / 2) / q.sum()
    mask = q > 0
    if cfg["kind"] == "ipf":
        x = q.copy()
        for _ in range(500):
            r = x.sum(1)
            x = x * np.divide(b, r, out=np.ones(NS), where=r > 0)[:, None]
            c = x.sum(0)
            x = x * np.divide(a, c, out=np.ones(NS), where=c > 0)[None, :]
    else:
        lam = cfg["lam"]
        qv = q[mask]

        def fun(v):
            x = np.zeros((NS, NS)); x[mask] = v
            r, c = x.sum(1) - b, x.sum(0) - a
            val = (r ** 2).sum() + (c ** 2).sum() + lam * (v * np.log(v / qv) - v + qv).sum()
            g = 2 * r[:, None] + 2 * c[None, :]
            return val, (g[mask] + lam * np.log(v / qv))
        res = minimize(fun, qv.copy(), jac=True, method="L-BFGS-B", bounds=[(1e-9, None)] * len(qv),
                       options=dict(maxiter=500))
        x = np.zeros((NS, NS)); x[mask] = res.x
    tri_lo = np.tril(np.ones((NS, NS)), -1)  # j < i
    rows, cols = x.sum(1), x.sum(0)
    p = np.where(rows > 0.05, (x * tri_lo).sum(1) / np.maximum(rows, 1e-12), np.nan)
    qh = np.where(cols > 0.05, (x * tri_lo).sum(0) / np.maximum(cols, 1e-12), np.nan)  # sum_{i>j} x_ij
    return p, qh


def build_prior(B_obs, A_obs, cfg):
    p0, q0 = static_prior()
    if cfg is None:
        return p0, q0, p0.copy(), q0.copy()
    ph, qh = p0.copy(), q0.copy()
    for h in range(NH):
        p, q = fit_hour(B_obs[:, h].astype(float), A_obs[:, h].astype(float), cfg)
        ph[:, h] = np.where(np.isfinite(p), np.clip(p, .01, .99), p0[:, h])
        qh[:, h] = np.where(np.isfinite(q), np.clip(q, .01, .99), q0[:, h])
    return ph.astype(np.float32), qh.astype(np.float32), p0, q0


def solve_day(date_str, cfg=None, epochs=1000, init_seed=None, diagnostics=None):
    """Baseline optimizer (non-headway boarding) with prior/init replaced by the OD-derived one."""
    torch.set_num_threads(1)
    nxt = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    curr = json.loads((gt.SUBWAY_DIR / f"{date_str}.json").read_text(encoding="utf-8"))
    nd = json.loads((gt.SUBWAY_DIR / f"{nxt}.json").read_text(encoding="utf-8")) if (gt.SUBWAY_DIR / f"{nxt}.json").exists() else None
    B_obs = np.zeros((NS, NH), np.float32); A_obs = np.zeros((NS, NH), np.float32)
    for sid_str, st in curr["stations"].items():
        sid = int(sid_str)
        if not 101 <= sid <= 122:
            continue
        for h, c in st.get("boardings", {}).items():
            if 5 <= int(h) <= 23: B_obs[sid - 101, gt.HOUR_TO_IDX[int(h)]] += c
        for h, c in st.get("alightings", {}).items():
            if 5 <= int(h) <= 23: A_obs[sid - 101, gt.HOUR_TO_IDX[int(h)]] += c
    if nd is not None:
        for sid_str, st in nd["stations"].items():
            sid = int(sid_str)
            if 101 <= sid <= 122:
                B_obs[sid - 101, gt.HOUR_TO_IDX[24]] += st.get("boardings", {}).get("0", 0)
                A_obs[sid - 101, gt.HOUR_TO_IDX[24]] += st.get("alightings", {}).get("0", 0)
    p_hat, q_hat, p_old, q_old = build_prior(B_obs, A_obs, cfg)

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
    idx_s = T([m["station_idx"] for m in meta], dtype=torch.long)
    idx_h = T([m["hour_idx"] for m in meta], dtype=torch.long)
    t_dir = T([float(m["dir_code"]) for m in meta])
    m_dest = T([float(m["is_destination"]) for m in meta]); m_orig = T([float(m["is_origin"]) for m in meta])

    pl0 = np.log(p_hat[1:-1] / (1 - p_hat[1:-1])); ql0 = np.log(q_hat[1:-1] / (1 - q_hat[1:-1]))
    if init_seed is not None:
        rng = np.random.default_rng(init_seed)
        pl0 += rng.normal(0, .25, pl0.shape).astype(np.float32)
        ql0 += rng.normal(0, .25, ql0.shape).astype(np.float32)
    p_logits = torch.nn.Parameter(T(pl0.astype(np.float32))); q_logits = torch.nn.Parameter(T(ql0.astype(np.float32)))
    prior_p, prior_q = T(p_hat[1:-1]), T(q_hat[1:-1])   # the OD-derived prior replaces the static one
    opt = torch.optim.Adam([p_logits, q_logits], lr=0.1)
    p_ident = ((nub > 0) & (ndb > 0))[1:-1]; q_ident = ((nua > 0) & (nda > 0))[1:-1]

    lengths = T([e - s for s, e, _ in slices]); offs = torch.arange(int(lengths.max()))[None, :]
    starts = T([s for s, _, _ in slices])[:, None]
    valid = offs < lengths[:, None]; gidx = (starts + offs).clamp(max=N - 1)

    def full_pq():
        z, o = torch.zeros((1, NH)), torch.ones((1, NH))
        return torch.cat([z, torch.sigmoid(p_logits), o]), torch.cat([o, torch.sigmoid(q_logits), z])

    def stops(p, q):
        pu, pd_ = gt.feasible_shares(p, nub, ndb); qu, qd = gt.feasible_shares(q, nua, nda)
        b_up, b_dn = pu * B_t / nub.clamp(min=1), pd_ * B_t / ndb.clamp(min=1)
        a_up, a_dn = qu * A_t / nua.clamp(min=1), qd * A_t / nda.clamp(min=1)
        up, dn = b_up[idx_s, idx_h] * (1 - m_dest), b_dn[idx_s, idx_h] * (1 - m_dest)
        b = (1 - t_dir) * up + t_dir * dn
        a = ((1 - t_dir) * a_up[idx_s, idx_h] + t_dir * a_dn[idx_s, idx_h]) * (1 - m_orig)
        return b, a

    def prior_loss():
        d1 = (torch.sigmoid(p_logits) - prior_p) ** 2; d2 = (torch.sigmoid(q_logits) - prior_q) ** 2
        return d1.mul(p_ident).sum() / p_ident.sum().clamp(min=1) + d2.mul(q_ident).sum() / q_ident.sum().clamp(min=1)

    best, best_ep, best_par = float("inf"), 0, None
    for ep in range(epochs):
        opt.zero_grad()
        p, q = full_pq(); b, a = stops(p, q)
        load = torch.cumsum((b - a)[gidx] * valid, dim=1)
        term = load.gather(1, (lengths - 1)[:, None]).squeeze(1)
        neg = torch.relu(-load[valid])
        loss = torch.mean(term ** 2) + torch.mean(neg ** 2) + 2.0 * prior_loss()
        v = float(loss.detach())
        if v < best:
            best, best_ep, best_par = v, ep + 1, (p_logits.detach().clone(), q_logits.detach().clone())
        loss.backward(); opt.step()
    with torch.no_grad():
        p_logits.copy_(best_par[0]); q_logits.copy_(best_par[1])
        p, q = full_pq(); b, a = stops(p, q)
    b, a = b.numpy().astype(np.float64), a.numpy().astype(np.float64)
    frame = pd.DataFrame(meta)
    frame["board"], frame["alight"] = b, a
    frame["raw_load"] = np.concatenate([np.cumsum(b[s:e] - a[s:e]) for s, e, _ in slices])
    frame["load"] = np.maximum(frame.raw_load, 0)
    pf, qf = p.numpy(), q.numpy()
    pid, qid = p_ident.numpy(), q_ident.numpy()
    w = (B_obs[1:-1] > 0) & pid
    wq = (A_obs[1:-1] > 0) & qid
    if diagnostics is not None:
        diagnostics.update(date=date_str, best_epoch=best_ep, best_loss=best, epochs_run=epochs,
                           board_observed_total=float(B_obs.sum()), alight_observed_total=float(A_obs.sum()),
                           board_allocated_total=float(b.sum()), alight_allocated_total=float(a.sum()),
                           p_dev_from_static=float(np.abs(pf[1:-1] - p_old[1:-1])[w].mean()),
                           q_dev_from_static=float(np.abs(qf[1:-1] - q_old[1:-1])[wq].mean()),
                           p_dev_from_hat=float(np.abs(pf[1:-1] - p_hat[1:-1])[w].mean()),
                           q_dev_from_hat=float(np.abs(qf[1:-1] - q_hat[1:-1])[wq].mean()),
                           p_hat_dev_from_static=float(np.abs(p_hat[1:-1] - p_old[1:-1])[w].mean()),
                           q_hat_dev_from_static=float(np.abs(q_hat[1:-1] - q_old[1:-1])[wq].mean()))
    return frame, dict(p_fit=pf, q_fit=qf, p_hat=p_hat, q_hat=q_hat, B=B_obs, A=A_obs)
