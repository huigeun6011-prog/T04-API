"""Model-based shift-and-stack timetable fit for line C, 2019-01-08 only (consistency check, not an independent validation).
Reuses lineC_direct / lineC_tracks / lineC_route_gate helpers. Output: outputs/hangzhou/lineC_stack/."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lineC_direct import direct_directions
from lineC_route_gate import DATE, ROOT, build_topology, corridor_order, graph_distances, read_tags
from lineC_tracks import find_daily_peaks, initial_intervals
import numpy as np
import pandas as pd
from scipy.ndimage import gaussian_filter1d, uniform_filter1d
from scipy.signal import find_peaks

OUT = ROOT / "outputs/hangzhou/lineC_stack"
DAY = 86_400
PAD = 8_000
WALK = 30                 # same common walk delay as the earlier method
TOL = 45
ADJ_MAX = 60              # max |cumulative adjustment| per station (s) -- the only data-fitted freedom besides train refs
ADJ_ITERS = 3
LAG = 45                  # search range of each iteration's lag (s)
Z_CLIP = 6.0
BASE_FLOOR = 1e-3         # tags/s floor of local baseline
STACK_RATIO = 1.8         # fixed before looking at fragmentation; sensitivity reported separately
STACK_DIST = 60
GATE_BOTH, GATE_SMALL = 0.60, 0.05
WIN = 2 * 30 * 60 + 1
NORM = uniform_filter1d(np.ones(DAY), WIN, mode="constant")


def zsignal(times):
    h = np.bincount(times, minlength=DAY).astype(float)
    sm = gaussian_filter1d(h, 10)
    base = uniform_filter1d(sm, WIN, mode="constant") / NORM
    return np.clip(sm / np.maximum(base, BASE_FLOOR), 0, Z_CLIP) * (h.sum() > 0)


def shifted(zp, off):
    """value of padded signal at tag time T0+off for T0 in 0..DAY-1."""
    s = PAD + int(round(off))
    return zp[s:s + DAY]


def stack(zps, offs):
    return np.mean([shifted(z, o) for z, o in zip(zps, offs)], axis=0)


def find_refs(S):
    base = uniform_filter1d(S, WIN, mode="constant") / NORM
    idx, pr = find_peaks(S, distance=STACK_DIST, height=STACK_RATIO * base, prominence=(None, None))
    return idx, S[idx] / base[idx]


def pipeline(Z, cum, vis, adj_fit=True):
    """Z: list of padded z-signals per station (direction order); cum: cumulative interval (s) per station;
    vis: indices of visible stations that have data. Returns refs T0, ref strength, adj (per station, s), stack."""
    adj = np.zeros(len(cum))
    zps = [Z[k] for k in vis]
    for it in range(ADJ_ITERS + 1):
        offs = [cum[k] + adj[k] + WALK for k in vis]
        S = stack(zps, offs)
        refs, strength = find_refs(S)
        if it == ADJ_ITERS or not adj_fit:
            break
        for k in vis:
            lags = np.arange(-LAG, LAG + 1)
            base_idx = refs + int(round(cum[k] + adj[k] + WALK))
            sc = np.array([Z[k][np.clip(PAD + base_idx + l, 0, len(Z[k]) - 1)].sum() for l in lags])
            sc = np.convolve(sc, np.ones(9) / 9, mode="same")           # smooth: avoid single-tag spikes
            adj[k] = np.clip(adj[k] + lags[int(np.argmax(sc))], -ADJ_MAX, ADJ_MAX)
    return refs, strength, adj, S


def interp_adj(adj, vis, n):
    return np.interp(np.arange(n), vis, adj[vis])


def support(pred, peaks):
    """True if a detected peak arrival lies within TOL of pred (array)."""
    if len(peaks) == 0:
        return np.zeros(len(pred), bool), np.full(len(pred), np.nan)
    j = np.clip(np.searchsorted(peaks, pred), 1, len(peaks) - 1)
    near = np.where(np.abs(peaks[j - 1] - pred) <= np.abs(peaks[j] - pred), peaks[j - 1], peaks[j])
    return np.abs(near - pred) <= TOL, near - pred


def frag_stats(obs_mat):
    """obs_mat: trains x stations bool (direction order). Same definition as the earlier method."""
    n_obs = obs_mat.sum(1)
    first = np.where(n_obs > 0, obs_mat.argmax(1), 0)
    last = np.where(n_obs > 0, obs_mat.shape[1] - 1 - obs_mat[:, ::-1].argmax(1), 0)
    near = (first <= 2) & (obs_mat.shape[1] - 1 - last <= 2) & (n_obs > 0)
    return dict(trains=len(obs_mat), both_ends_within_2=float(near.mean()), small_1_2_observed=float((n_obs <= 2).mean()),
                observed_zero=float((n_obs == 0).mean()), median_obs=float(np.median(n_obs)),
                obs_hist={int(k): int(v) for k, v in zip(*np.unique(n_obs, return_counts=True))})


def build_direction(anchors, stations):
    direction = f"toward_{stations[-1]}"
    sample = anchors.loc[anchors.direction.eq(direction)]
    raw = {s: g.exit_seconds.to_numpy() for s, g in sample.groupby("exit_station")}
    Z = [np.pad(zsignal(raw.get(s, np.empty(0, int))), PAD) for s in stations]
    has = [k for k, s in enumerate(stations) if len(raw.get(s, [])) > 0]
    peaks, _ = find_daily_peaks(sample, stations)
    pk = [p.arrival_seconds.to_numpy() for p in peaks]
    initial, intercept, n_od = initial_intervals(sample, stations)
    cum = np.r_[0, np.cumsum(initial)]
    return dict(direction=direction, stations=stations, Z=Z, has=has, pk=pk, cum=cum, intercept=intercept, n_od=n_od,
                n_exits={s: len(raw.get(s, [])) for s in stations})


def make_trains(D, vis, adj, refs, strength, pk=None):
    """in-day trains only: every station arrival (T0+cum+adj) inside the day. Returns kept mask, arrival matrix."""
    pk = D["pk"] if pk is None else pk
    arr = refs[:, None] + (D["cum"] + adj)[None, :]
    keep = (arr.min(1) >= 0) & (arr.max(1) < DAY)
    return keep, arr


def observed_matrix(arr, pk, cols):
    return np.column_stack([support(arr[:, k], pk[k])[0] for k in cols])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(20190108)
    gate_line, trips, all_exits = read_tags()
    tracks, membership, _, _, _ = build_topology(gate_line)
    graph_distances({"C": tracks["C"]})
    corridor = corridor_order(tracks["C"])
    active = [s for s in corridor if gate_line.get(s) == "C"]
    anchors = direct_directions(trips, corridor, membership)
    shared = {s for s in active if len(membership[s]) > 1}
    res = {"date": DATE, "stations": active, "shared_stations": sorted(int(s) for s in shared)}
    events, frag_rows, hold = [], {}, {}
    dirs = {}
    for stations in (active, active[::-1]):
        D = build_direction(anchors, stations)
        dirs[D["direction"]] = D
    # ---------- main fit (all stations) ----------
    pooled_obs, summary = [], {}
    for name, D in dirs.items():
        n = len(D["stations"])
        refs, strength, adj, S = pipeline(D["Z"], D["cum"], D["has"])
        keep, arr = make_trains(D, D["has"], adj, refs, strength)
        obs = observed_matrix(arr[keep], D["pk"], range(n))
        # stations with no exits in this direction (origin terminal) cannot be observed: counted as unobserved, as before
        fr = frag_stats(obs)
        sup_near = [support(arr[keep][:, k], D["pk"][k])[1] for k in range(n)]
        pooled_obs.append(obs)
        hw = np.diff(np.sort(refs[keep]))
        hours = (np.sort(refs[keep])[1:] // 3600).astype(int)
        summary[name] = dict(
            refs_total=int(len(refs)), refs_in_day=int(keep.sum()), refs_dropped_boundary=int((~keep).sum()),
            intercept_s=D["intercept"], n_od=D["n_od"], cum_end_s=float(D["cum"][-1]), adj_s=[float(x) for x in adj],
            adj_abs_max=float(np.abs(adj).max()), adj_at_limit=int((np.abs(adj) >= ADJ_MAX).sum()),
            frag=fr,
            headway_s=dict(median=float(np.median(hw)), q25=float(np.quantile(hw, .25)), q75=float(np.quantile(hw, .75)),
                           lt_120=float((hw < 120).mean()), gt_600=float((hw > 600).mean()),
                           cv=float(hw.std() / hw.mean())),
            headway_median_by_hour={int(h): float(np.median(hw[hours == h])) for h in np.unique(hours) if (hours == h).sum() >= 3},
            median_abs_resid_by_station_s={str(D["stations"][k]): (float(np.nanmedian(np.abs(sup_near[k][np.isfinite(sup_near[k])])))
                                                                  if np.isfinite(sup_near[k]).any() else None) for k in range(n)})
        # events
        a, ok = arr[keep], obs
        st = strength[keep]
        for i in range(len(a)):
            tid = f"C-{DATE.replace('-', '')}-{name}-S{i + 1:04d}"
            for k in range(n):
                if D["stations"][k] == 54:
                    continue
                events.append((tid, name, D["stations"][k], a[i, k], bool(ok[i, k]), st[i], k in D["has"]))
        # figure data
        D["_fig"] = (refs[keep], arr[keep], obs, S)
    both = np.vstack([np.pad(o, ((0, 0), (0, 0))) for o in pooled_obs])
    summary["pooled"] = frag_stats(both)
    # ---------- null: each station's signal and peaks circularly shifted independently, then the same pipeline ----------
    nulls = []
    for rep in range(3):
        rows = []
        for name, D in dirs.items():
            n = len(D["stations"])
            Zn, pkn = [], []
            for k in range(n):
                sh = int(rng.integers(900, 3000)) * rng.choice([-1, 1])
                core = np.roll(D["Z"][k][PAD:PAD + DAY], sh)
                Zn.append(np.pad(core, PAD))
                pkn.append(np.sort((D["pk"][k] + sh) % DAY))
            refs, strength, adj, S = pipeline(Zn, D["cum"], D["has"])
            keep, arr = make_trains(D, D["has"], adj, refs, strength)
            rows.append(observed_matrix(arr[keep], pkn, range(n)))
        nulls.append(frag_stats(np.vstack(rows)))
    summary["null_station_shift_3reps"] = nulls
    # ---------- holdout ----------
    interior = [k for k in range(1, len(active) - 1) if active[k] not in shared and active[k] != 54]
    hold_rows = []
    for fold in range(3):
        hid = {active[k] for i, k in enumerate(interior) if i % 3 == fold}
        for name, D in dirs.items():
            st = D["stations"]
            hidx = [k for k, s in enumerate(st) if s in hid]
            vis = [k for k in D["has"] if k not in hidx]
            refs, strength, adj, S = pipeline(D["Z"], D["cum"], vis)
            full_adj = interp_adj(adj, np.array(vis), len(st))
            keep, arr = make_trains(D, vis, full_adj, refs, strength)
            arr = arr[keep]
            for k in hidx:
                pk = D["pk"][k]
                ctrl_rec = []
                pred = arr[:, k]
                rec = float(support_rec(pred, pk))
                for _ in range(200):
                    d = rng.uniform(120, 600) * rng.choice([-1, 1])
                    ctrl_rec.append(float(support_rec(pred + d, pk)))
                prec = float(support(pred, pk)[0].mean())
                prec_c = float(np.mean([support(pred + rng.uniform(120, 600) * rng.choice([-1, 1]), pk)[0].mean() for _ in range(50)]))
                hold_rows.append(dict(fold=fold, direction=name, stationID=int(st[k]), peaks=len(pk), trains=len(pred),
                                      recall=rec, recall_ctrl_mean=float(np.mean(ctrl_rec)), recall_ctrl_p95=float(np.quantile(ctrl_rec, .95)),
                                      precision=prec, precision_ctrl_mean=prec_c, exits=D["n_exits"][st[k]]))
    H = pd.DataFrame(hold_rows)
    H.to_csv(OUT / "holdout_by_station.csv", index=False, float_format="%.4f")
    def agg(g):
        w = g.peaks
        return pd.Series(dict(cells=len(g), peaks=int(w.sum()), recall=np.average(g.recall, weights=w) if w.sum() else np.nan,
                              ctrl_mean=np.average(g.recall_ctrl_mean, weights=w) if w.sum() else np.nan,
                              ctrl_p95_mean=np.average(g.recall_ctrl_p95, weights=w) if w.sum() else np.nan,
                              precision=g.precision.mean(), precision_ctrl=g.precision_ctrl_mean.mean()))
    summary["holdout"] = {"pooled": agg(H).to_dict(), "by_fold": {int(f): agg(g).to_dict() for f, g in H.groupby("fold")},
                          "by_direction": {d: agg(g).to_dict() for d, g in H.groupby("direction")}}
    # ---------- sensitivity (informational only; main setting stays fixed) ----------
    global STACK_RATIO
    sens = {}
    main_ratio = STACK_RATIO
    for r in (1.5, 2.5):
        STACK_RATIO = r
        rows = []
        for name, D in dirs.items():
            refs, strength, adj, S = pipeline(D["Z"], D["cum"], D["has"])
            keep, arr = make_trains(D, D["has"], adj, refs, strength)
            rows.append(observed_matrix(arr[keep], D["pk"], range(len(D["stations"]))))
        sens[str(r)] = frag_stats(np.vstack(rows))
    STACK_RATIO = main_ratio
    summary["sensitivity_stack_ratio"] = sens
    summary["gate"] = dict(both_ends_min=GATE_BOTH, small_max=GATE_SMALL,
                           passed=bool(summary["pooled"]["both_ends_within_2"] >= GATE_BOTH and summary["pooled"]["small_1_2_observed"] <= GATE_SMALL))
    res.update(summary)
    (OUT / "stack_result.json").write_text(json.dumps(res, indent=2, default=float), encoding="utf-8")
    ev = pd.DataFrame(events, columns=["train_id", "direction", "stationID", "arrival_seconds", "observed_peak_within_45s", "stack_strength", "station_has_exits"])
    ev["arrival_time"] = pd.Timestamp(DATE) + pd.to_timedelta(ev.arrival_seconds.round(), unit="s")
    ev["quality_gate"] = "passed" if summary["gate"]["passed"] else "failed_fragmentation"
    ev.drop(columns="arrival_seconds").to_csv(OUT / "candidate_arrival_events_stack.csv", index=False, float_format="%.3f")
    # ---------- figure data (rendered by lineC_stack_figures.py with Plotly) ----------
    fd = {}
    for name, D in dirs.items():
        refs, arr, obs, S = D["_fig"]
        sel = (refs > 10 * 3600) & (refs < 11 * 3600)
        fd[name] = dict(stations=[int(x) for x in D["stations"]], refs=refs.tolist(), arr_10_11=arr[sel].round(1).tolist(),
                        obs_10_11=obs[sel].tolist(), n_obs=obs.sum(1).tolist(),
                        peaks={str(D["stations"][k]): [float(v) for v in p[(p > 9.5 * 3600) & (p < 12 * 3600)]] for k, p in enumerate(D["pk"])})
    fd["holdout"] = H.groupby("stationID")[["recall", "recall_ctrl_mean"]].mean().reset_index().to_dict("list")
    (OUT / "fig_data.json").write_text(json.dumps(fd), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("pooled", "gate", "null_station_shift_3reps", "holdout", "sensitivity_stack_ratio")}, indent=1, default=float))
    for name in dirs:
        s = summary[name]
        print(name, s["refs_in_day"], s["refs_dropped_boundary"], s["adj_abs_max"], s["adj_at_limit"], s["headway_s"], s["frag"]["both_ends_within_2"], s["frag"]["small_1_2_observed"], s["frag"]["median_obs"])


def support_rec(pred, peaks):
    """fraction of detected peaks (arrival times) that have a predicted arrival within TOL."""
    if len(peaks) == 0:
        return np.nan
    pred = np.sort(pred)
    j = np.clip(np.searchsorted(pred, peaks), 1, len(pred) - 1)
    near = np.minimum(np.abs(pred[j - 1] - peaks), np.abs(pred[j] - peaks))
    return float((near <= TOL).mean())


if __name__ == "__main__":
    main()
