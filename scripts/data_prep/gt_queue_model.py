"""Experimental queue + capacity boarding model for the GT estimator (opt-in, NOT production).

Definition
- Hourly tap-ins are gate ARRIVALS, spread uniformly in time (same integration as the existing
  boarding-headway option: gt_assumptions.boarding_exposures). Split between directions by p as before.
- Per (station, direction) the platform holds a queue. At each scheduled departure (non-terminal stop):
      waiting  = arrivals since previous departure of that direction + carryover queue
      room     = C - max(load_on_train_after_alighting, 0)
      boarding = softmin(waiting, room)          (smooth, eps=0.1 person)
      carryover= waiting - boarding              (passes to the next same-direction train, across hours)
- First departure of the day starts with an empty queue (arrivals counted from 05:00 opening);
  carryover left after the last departure and gate counts after the last departure are slack.
- Alighting, p/q direction split, soft terminal-zero / negative-load penalties, prior, Adam(lr .1),
  best-iterate restore are exactly as in generate_ground_truth.process_single_date.
- Fully differentiable; events are processed in dependency levels (train's previous stop, station queue's
  previous train), so each level is vectorised.  capacity=None => infinite capacity => identical to
  boarding_headway (sanity-checked in the experiment).
Peak cases are never read here.
"""
import json
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import torch
import generate_ground_truth as gt
from gt_assumptions import boarding_exposures

EPS = 0.1


def _smin(a, b):
    return 0.5 * (a + b - torch.sqrt((a - b) ** 2 + EPS ** 2))


def solve_day(date_str, capacity=None, epochs=1000, init_seed=None, diagnostics=None):
    torch.set_num_threads(1)
    device = torch.device("cpu")
    nxt = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    curr = json.loads((gt.SUBWAY_DIR / f"{date_str}.json").read_text(encoding="utf-8"))
    nxt_path = gt.SUBWAY_DIR / f"{nxt}.json"
    nxt_data = json.loads(nxt_path.read_text(encoding="utf-8")) if nxt_path.exists() else None
    NS, NH = gt.N_STATIONS, gt.N_HOURS
    B_obs = np.zeros((NS, NH), np.float32)
    A_obs = np.zeros((NS, NH), np.float32)
    for sid_str, s in curr["stations"].items():
        sid = int(sid_str)
        if not 101 <= sid <= 122:
            continue
        for h, c in s.get("boardings", {}).items():
            if 5 <= int(h) <= 23:
                B_obs[sid - 101, gt.HOUR_TO_IDX[int(h)]] += c
        for h, c in s.get("alightings", {}).items():
            if 5 <= int(h) <= 23:
                A_obs[sid - 101, gt.HOUR_TO_IDX[int(h)]] += c
    if nxt_data is not None:
        for sid_str, s in nxt_data["stations"].items():
            sid = int(sid_str)
            if 101 <= sid <= 122:
                B_obs[sid - 101, gt.HOUR_TO_IDX[24]] += s.get("boardings", {}).get("0", 0)
                A_obs[sid - 101, gt.HOUR_TO_IDX[24]] += s.get("alightings", {}).get("0", 0)

    day_type = gt.get_day_type(date_str)
    trains = gt.get_subway_trains(date_str, day_type)
    n_ub, n_ua, n_db, n_da = (np.zeros((NS, NH), np.float32) for _ in range(4))
    meta, slices = [], []
    for t in trains:
        d = 0 if t["direction"] == "상행" else 1
        n = len(t["stops"])
        start = len(meta)
        for i, st in enumerate(t["stops"]):
            s_idx = gt.STATION_TO_IDX[st["station"]]
            hh = gt.normalize_hour(int(st["time"].split(":")[0]))
            h_idx = gt.HOUR_TO_IDX[hh]
            org, dest = i == 0, i == n - 1
            meta.append(dict(train_id=t["train_id"], direction=t["direction"], dir_code=d, station=st["station"],
                             station_idx=s_idx, time=st["time"], hour=hh, hour_idx=h_idx,
                             is_origin=int(org), is_destination=int(dest)))
            (n_ub if d == 0 else n_db)[s_idx, h_idx] += 0 if dest else 1
            (n_ua if d == 0 else n_da)[s_idx, h_idx] += 0 if org else 1
        slices.append((start, len(meta), d))
    N = len(meta)
    T = lambda x, **k: torch.tensor(x, device=device, **k)
    B_t, A_t = T(B_obs), T(A_obs)
    nub, nua, ndb, nda = T(n_ub), T(n_ua), T(n_db), T(n_da)
    idx_s = T([m["station_idx"] for m in meta], dtype=torch.long)
    idx_h = T([m["hour_idx"] for m in meta], dtype=torch.long)
    t_dir = T([float(m["dir_code"]) for m in meta])
    m_dest = T([float(m["is_destination"]) for m in meta])
    m_orig = T([float(m["is_origin"]) for m in meta])

    edges, coverage, both_cov = boarding_exposures(meta)
    E = np.asarray(edges, np.float64)
    e_stop, e_st, e_h = (T(E[:, k], dtype=torch.long) for k in (0, 1, 2))
    e_dir, e_both, e_only = (T(E[:, k], dtype=torch.float32) for k in (3, 4, 5))

    # --- dependency levels -------------------------------------------------
    def minute(m):
        hh, mm = map(int, m["time"].split(":"))
        return (24 if hh == 0 else hh) * 60 + mm
    mins = [minute(m) for m in meta]
    pred_train = np.full(N, N)
    pred_queue = np.full(N, N)
    last_in_chain, last_in_train = {}, {}
    order = sorted(range(N), key=lambda i: (mins[i], i))
    dup = 0
    for i in order:
        m = meta[i]
        if i > 0 and meta[i - 1]["train_id"] == m["train_id"]:
            pred_train[i] = i - 1
        if not m["is_destination"]:
            key = (m["station_idx"], m["dir_code"])
            if key in last_in_chain:
                pred_queue[i] = last_in_chain[key]
                dup += mins[last_in_chain[key]] == mins[i]
            last_in_chain[key] = i
    level = np.zeros(N, int)
    for i in order:  # (time,index) order is topological
        l = 0
        for p_ in (pred_train[i], pred_queue[i]):
            if p_ < N:
                l = max(l, level[p_] + 1)
        level[i] = l
    levels = [T(np.where(level == l)[0], dtype=torch.long) for l in range(level.max() + 1)]
    pt, pq_ = T(pred_train, dtype=torch.long), T(pred_queue, dtype=torch.long)
    tail = T([i for i in last_in_chain.values()], dtype=torch.long)

    # --- parameters, priors (copied from the baseline solver) ---------------
    pp = np.clip(np.array([[s / (NS - 1)] * NH for s in range(NS)], np.float32), .01, .99)
    qp = np.clip(1 - np.array([[s / (NS - 1)] * NH for s in range(NS)], np.float32), .01, .99)
    pl0 = np.log(pp[1:-1] / (1 - pp[1:-1]))
    ql0 = np.log(qp[1:-1] / (1 - qp[1:-1]))
    if init_seed is not None:
        rng = np.random.default_rng(init_seed)
        pl0 += rng.normal(0, .25, pl0.shape).astype(np.float32)
        ql0 += rng.normal(0, .25, ql0.shape).astype(np.float32)
    p_logits = torch.nn.Parameter(T(pl0))
    q_logits = torch.nn.Parameter(T(ql0))
    prior_p, prior_q = T(pp[1:-1]), T(qp[1:-1])
    opt = torch.optim.Adam([p_logits, q_logits], lr=0.1)
    p_ident = T(both_cov > 0)[1:-1]
    q_ident = ((nua > 0) & (nda > 0))[1:-1]

    def full_pq():
        z, o = torch.zeros((1, NH)), torch.ones((1, NH))
        return (torch.cat([z, torch.sigmoid(p_logits), o]), torch.cat([o, torch.sigmoid(q_logits), z]))

    def alight_stops(q):
        q_up, q_dn = gt.feasible_shares(q, nua, nda)
        a_up = q_up * A_t / nua.clamp(min=1)
        a_dn = q_dn * A_t / nda.clamp(min=1)
        return ((1 - t_dir) * a_up[idx_s, idx_h] + t_dir * a_dn[idx_s, idx_h]) * (1 - m_orig)

    def arrivals(p):
        up = p[e_st, e_h]
        share = (1 - e_dir) * up + e_dir * (1 - up)
        return torch.zeros(N).scatter_add(0, e_stop, B_t[e_st, e_h] * (share * e_both + e_only))

    def simulate(p, q):
        a = alight_stops(q)
        arr = arrivals(p)
        load = torch.zeros(N + 1); left = torch.zeros(N + 1); board = torch.zeros(N + 1)
        for e in levels:
            load_in = load[pt[e]]
            W = arr[e] + left[pq_[e]]
            if capacity is None:
                b = W
            else:
                room = (capacity - torch.relu(load_in - a[e])).clamp(min=0)
                b = _smin(W, room).clamp(min=0)
            board = board.index_put((e,), b)
            left = left.index_put((e,), W - b)
            load = load.index_put((e,), load_in - a[e] + b)
        return load[:N], board[:N], left[:N], a

    def prior_loss():
        d1 = (torch.sigmoid(p_logits) - prior_p) ** 2
        d2 = (torch.sigmoid(q_logits) - prior_q) ** 2
        return ((d1 * p_ident).sum() / p_ident.sum().clamp(min=1) + (d2 * q_ident).sum() / q_ident.sum().clamp(min=1))

    n_tr = len(slices)
    best, best_epoch, best_par, hist = float("inf"), 0, None, []
    for ep in range(epochs):
        opt.zero_grad()
        p, q = full_pq()
        load, board, left, a = simulate(p, q)
        loss = ((load * m_dest) ** 2).sum() / n_tr + (torch.relu(-load) ** 2).mean() + 2.0 * prior_loss()
        v = float(loss.detach()); hist.append(v)
        if v < best:
            best, best_epoch, best_par = v, ep + 1, (p_logits.detach().clone(), q_logits.detach().clone())
        loss.backward(); opt.step()
    with torch.no_grad():
        p_logits.copy_(best_par[0]); q_logits.copy_(best_par[1])
        p, q = full_pq()
        load, board, left, a = simulate(p, q)
    load, board, left, a = (x.numpy().astype(np.float64) for x in (load, board, left, a))
    frame = pd.DataFrame(meta)
    frame["board"], frame["alight"], frame["raw_load"] = board, a, load
    frame["load"] = np.maximum(load, 0)
    frame["carryover_after"] = left
    terminal = frame.loc[frame.is_destination == 1, "raw_load"].to_numpy()
    leftover = float(left[tail.numpy()].sum())
    gate_after_last = float((B_obs * (1 - coverage)).sum())
    unall_a = float((A_obs * ((nua + nda) == 0).numpy()).sum())
    if diagnostics is not None:
        diagnostics.update(date=date_str, capacity=capacity, best_epoch=best_epoch, best_loss=best, epochs_run=len(hist),
                           n_levels=len(levels), equal_time_departures=int(dup),
                           board_observed_total=float(B_obs.sum()), alight_observed_total=float(A_obs.sum()),
                           board_allocated_total=float(board.sum()), alight_allocated_total=float(a.sum()),
                           board_leftover_queue_end_of_day=leftover, board_gate_after_last_departure=gate_after_last,
                           alight_unallocated_total=unall_a)
    return frame
