"""Pool several days of line-C direct anchors into one timetable per day group, fit per-station/direction lags, and report how much of the
tags it explains (not a validation). Rules frozen in outputs/hangzhou/lineC_pool/criteria.md. Reuses lineC_stack / lineC_direct_check."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lineC_stack as ST
import lineC_direct_check as DC
from lineC_route_gate import ROOT, build_topology, corridor_order, graph_distances, read_tags
import numpy as np
import pandas as pd

CACHE = ROOT / "outputs/hangzhou/cache"
OUT = ROOT / "outputs/hangzhou/lineC_pool"
DAY, PAD, WALK, DWELL, MAXGAP = ST.DAY, ST.PAD, 30, 30, 600
dstr = lambda i: f"2019-01-{i:02d}"
WEEKDAYS = [dstr(i) for i in (2, 3, 4, 7, 8, 9, 10, 11, 14, 15, 16, 17, 18, 21, 22, 23, 24, 25)]
WEEKENDS = [dstr(i) for i in (5, 6, 12, 13, 19, 20)]
HOLIDAY = dstr(1)
M_MIN, M_MARGIN, TOL = 0.60, 0.25, 45
SHIFTS, EPSS = np.arange(-15, 16, 5), np.array([-.02, -.01, 0, .01, .02])
MIN_GAP, K_SHRINK, TAIL_N = 45, 200, 5
rng = np.random.default_rng(20190108)


def load_day(date, first, last):
    z = np.load(CACHE / f"pool_anchors_{date}.npz")
    return pd.DataFrame(dict(entry_station=z["e"].astype(int), exit_station=z["x"].astype(int), exit_seconds=z["X"].astype(int),
                             minutes=z["minutes"].astype(float), direction=np.where(z["d"] == 1, f"toward_{last}", f"toward_{first}")))


# ---------- 1. day check ----------
def day_refs(df, active):
    out = {}
    for stations in (active, active[::-1]):
        D = ST.build_direction(df, stations)
        refs, strength, adj, S = ST.pipeline(D["Z"], D["cum"], D["has"])
        out[D["direction"]] = np.sort(refs[(refs >= 6 * 3600) & (refs < 22 * 3600)])
    return out


def match(A, B, shift=0.0):
    r = []
    for d in A:
        a, b = A[d], np.sort(B[d] + shift)
        def frac(u, v):
            j = np.clip(np.searchsorted(v, u), 1, len(v) - 1)
            return float((np.minimum(np.abs(v[j - 1] - u), np.abs(v[j] - u)) <= TOL).mean())
        r.append(0.5 * (frac(a, b) + frac(b, a)))
    return float(np.mean(r))


def chance(A, B):
    return float(np.mean([match(A, B, rng.choice([-1, 1]) * rng.uniform(60, 225)) for _ in range(5)]))


def select(days, R):
    cur, log = list(days), []
    while True:
        sc = {d: float(np.median([match(R[d], R[o]) for o in cur if o != d])) for d in cur}
        ch = {d: float(np.median([chance(R[d], R[o]) for o in cur if o != d])) for d in cur}
        bad = [d for d in cur if not (sc[d] >= M_MIN and sc[d] >= ch[d] + M_MARGIN)]
        log.append(dict(days=list(cur), score=sc, chance=ch))
        if not bad or len(cur) < 3:
            return cur, log
        cur.remove(min(bad, key=lambda d: sc[d]))


# ---------- 2. pooled timetable ----------
def refine_trains(D, refs, offs):
    vis = D["has"]
    Zs, cols = [D["Z"][k] for k in vis], offs[vis]
    def obj(s, e):
        idx = np.clip((refs[:, None] + s + cols[None, :] * (1 + e) + WALK).round().astype(int) + PAD, 0, len(Zs[0]) - 1)
        return sum(Zs[j][idx[:, j]] for j in range(len(vis)))
    best, bs, be = obj(0, 0), np.zeros(len(refs)), np.zeros(len(refs))
    for s in SHIFTS:
        for e in EPSS:
            o = obj(s, e)
            up = o > best + 1e-9
            best, bs, be = np.where(up, o, best), np.where(up, s, bs), np.where(up, e, be)
    # order preservation: consecutive trains >= MIN_GAP apart at every station; otherwise revert to (0,0)
    arr = lambda i, s, e: refs[i] + s + offs * (1 + e)
    prev, viol = None, 0
    for i in range(len(refs)):
        cand = arr(i, bs[i], be[i])
        nxt = arr(i + 1, 0, 0) if i + 1 < len(refs) else None
        ok = lambda a: (prev is None or (a - prev).min() >= MIN_GAP) and (nxt is None or (nxt - a).min() >= MIN_GAP)
        if not ok(cand):
            bs[i], be[i], cand = 0, 0, arr(i, 0, 0)
            viol += not ok(cand)
        prev = cand
    return refs + bs, be, int(((bs != 0) | (be != 0)).sum()), viol


def fit_tables(anchors, active, refine):
    dirs, tabs, info = {}, {}, {}
    for stations in (active, active[::-1]):
        D = ST.build_direction(anchors, stations)
        dirs[D["direction"]] = D
    pooled_obs = []
    for name, D in dirs.items():
        n = len(D["stations"])
        refs, strength, adj, S = ST.pipeline(D["Z"], D["cum"], D["has"])
        offs = D["cum"] + adj
        t0, eps, moved, viol = (refs.astype(float), np.zeros(len(refs)), 0, 0)
        if refine:
            t0, eps, moved, viol = refine_trains(D, refs, offs)
        arr = t0[:, None] + offs[None, :] * (1 + eps[:, None])
        keep = (arr.min(1) >= 0) & (arr.max(1) < DAY)
        obs = ST.observed_matrix(arr[keep], D["pk"], range(n))
        pooled_obs.append(obs)
        has_ex = np.array([D["n_exits"][s] > 0 for s in D["stations"]])
        tail = np.zeros(int(keep.sum()), bool)
        for i, row in enumerate(obs):
            r = row[has_ex][::-1]
            run = int(np.argmax(r)) if r.any() else len(r)
            tail[i] = run >= TAIL_N
        tabs[name] = dict(stations=list(D["stations"]), arr=arr[keep], refs=t0[keep])
        info[name] = dict(obs=obs, tail=tail, strength=strength[keep], moved=moved, order_violations=viol, dropped=int((~keep).sum()),
                          peaks=int(sum(len(p) for p in D["pk"])), cum_end=float(offs[-1]))
    fr = ST.frag_stats(np.vstack(pooled_obs))
    return dirs, tabs, info, fr


# ---------- 3. lags + passenger evaluation ----------
class PaxSet:
    def __init__(self, df, active, day=None):
        self.e, self.x = df.entry_station.to_numpy(), df.exit_station.to_numpy()
        self.X = df.exit_seconds.to_numpy().astype(float)
        self.E = self.X - df.minutes.to_numpy() * 60
        self.d = (df.direction.to_numpy() == f"toward_{active[-1]}").astype(int)
        self.day = np.zeros(len(df), int) if day is None else day
        s = pd.Series(np.arange(len(df)))
        self.gdx = s.groupby([self.d, self.x]).indices
        self.gde = s.groupby([self.d, self.e]).indices
        self.gx = s.groupby(self.x).indices
        self.n = len(df)


def prep(tabs):
    P = {}
    for lab, t in tabs.items():
        col = np.full(100, -1)
        for k, s in enumerate(t["stations"]):
            col[s] = k
        order = np.argsort(t["arr"], axis=0)
        P[lab] = dict(arr=t["arr"], col=col, order=order, vals=np.take_along_axis(t["arr"], order, axis=0), n=len(t["stations"]))
    return P


def evaluate(tabs, ps, active, Lout, Lin, dwell=DWELL):
    P = prep(tabs)
    lab_of = {0: f"toward_{active[0]}", 1: f"toward_{active[-1]}"}
    wait, ok, dm = np.full(ps.n, np.nan), np.zeros(ps.n, bool), np.full(ps.n, np.nan)
    for (di, x), idx in ps.gdx.items():
        lab = lab_of[di]; t = P[lab]; k = t["col"][x]
        v = t["vals"][:, k] + Lout[lab][k]
        j = np.searchsorted(v, ps.X[idx], side="right") - 1
        gap = np.where(j >= 0, ps.X[idx] - v[np.clip(j, 0, None)], np.inf)
        good = gap <= MAXGAP
        tr = t["order"][np.clip(j, 0, None), k]
        ec = t["col"][ps.e[idx]]
        D0 = t["arr"][tr, ec] + dwell - Lin[lab][ec]
        wait[idx] = np.where(good, D0 - ps.E[idx], np.nan)
        ok[idx] = good
    labs = list(lab_of.values())
    for x, idx in ps.gx.items():
        gaps = []
        for lab in labs:
            t = P[lab]; k = t["col"][x]
            v = t["vals"][:, k] + Lout[lab][k]
            j = np.searchsorted(v, ps.X[idx], side="right") - 1
            gaps.append(np.where(j >= 0, ps.X[idx] - v[np.clip(j, 0, None)], np.inf))
        gaps = np.column_stack(gaps)
        has = gaps.min(1) <= MAXGAP
        dm[idx] = np.where(has, (gaps.argmin(1) == ps.d[idx]).astype(float), np.nan)
    return wait, ok, dm


def metrics(wait, ok, dm, mask):
    w = wait[mask & ok]
    return dict(n=int(mask.sum()), assignable=float(ok[mask].mean()), neg=float((w < 0).mean()), window=float(((w >= 0) & (w <= 600)).mean()),
                dir_match=float(np.nanmean(dm[mask])), q05=float(np.quantile(w, .05)), q50=float(np.quantile(w, .5)), q95=float(np.quantile(w, .95)))


def const_lags(tabs, out=WALK, inn=0.0):
    return ({l: np.full(len(t["stations"]), float(out)) for l, t in tabs.items()}, {l: np.full(len(t["stations"]), float(inn)) for l, t in tabs.items()})


def shrink(raw, n, default):
    raw, n = np.asarray(raw, float), np.asarray(n, float)
    prior = np.nanmedian(raw[n >= K_SHRINK]) if (n >= K_SHRINK).any() else default
    r0 = np.where(np.isfinite(raw), raw, prior)
    return (n * r0 + K_SHRINK * prior) / (n + K_SHRINK), raw


def fit_lags(tabs, ps, active):
    P = prep(tabs)
    lab_of = {0: f"toward_{active[0]}", 1: f"toward_{active[-1]}"}
    Lout, Lin, rows = {}, {}, []
    for di, lab in lab_of.items():
        t = tabs[lab]; p = P[lab]; ns = len(t["stations"])
        raw, n = np.full(ns, np.nan), np.zeros(ns)
        for k, s in enumerate(t["stations"]):
            idx = ps.gdx.get((di, s))
            if idx is None:
                continue
            v = np.sort(t["arr"][:, k])
            j = np.searchsorted(v, ps.X[idx] + 90, side="right") - 1
            dl = ps.X[idx] - v[np.clip(j, 0, None)]
            m = (j >= 0) & (dl <= 180)
            n[k] = m.sum()
            if m.sum() >= 20:
                raw[k] = np.quantile(dl[m], .05)
        Lout[lab], raw_out = shrink(raw, n, WALK)
        rows.append((lab, "out", raw_out, n))
    wait, ok, _ = evaluate(tabs, ps, active, Lout, {l: np.zeros(len(t["stations"])) for l, t in tabs.items()})
    for di, lab in lab_of.items():
        t = tabs[lab]; p = P[lab]; ns = len(t["stations"])
        raw, n = np.full(ns, np.nan), np.zeros(ns)
        for k, s in enumerate(t["stations"]):
            idx = ps.gde.get((di, s))
            if idx is None:
                continue
            m = ok[idx]
            n[k] = m.sum()
            if m.sum() >= 20:
                raw[k] = np.quantile(wait[idx][m], .05)
        Lin[lab], raw_in = shrink(raw, n, 0.0)
        rows.append((lab, "in", raw_in, n))
    table = []
    for lab, kind, raw, n in rows:
        L = Lout if kind == "out" else Lin
        for k, s in enumerate(tabs[lab]["stations"]):
            table.append(dict(direction=lab, stationID=int(s), kind=kind, n=int(n[k]), raw_s=float(raw[k]), lag_s=float(L[lab][k])))
    return Lout, Lin, pd.DataFrame(table)


def eval_group(tabs, ps, active, Lout, Lin, days=None):
    wait, ok, dm = evaluate(tabs, ps, active, Lout, Lin)
    res = {"all": metrics(wait, ok, dm, np.ones(ps.n, bool))}
    if days is not None:
        for i, d in enumerate(days):
            res[d] = metrics(wait, ok, dm, ps.day == i)
    return res


def sub(ps_df, frac):
    return ps_df.sample(frac=frac, random_state=1)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    gate, trips, _ = read_tags()
    tracks, membership, _, _, _ = build_topology(gate)
    corridor = corridor_order(tracks["C"])
    active = [s for s in corridor if gate.get(s) == "C"]
    first, last = active[0], active[-1]
    DF = {d: load_day(d, first, last) for d in [HOLIDAY] + WEEKDAYS + WEEKENDS}
    res = {}

    # ---- 1. day check ----
    R = {d: day_refs(DF[d], active) for d in DF}
    wd, wd_log = select(WEEKDAYS, R)
    we, we_log = select(WEEKENDS, R)
    rows = []
    for cls, cand, log, kept in (("weekday", WEEKDAYS, wd_log, wd), ("weekend", WEEKENDS, we_log, we)):
        first_log = log[0]
        for d in cand:
            fin = log[-1]
            rows.append(dict(date=d, cls=cls, trains_06_22=int(sum(len(v) for v in R[d].values())), score_first_pass=first_log["score"][d],
                             chance_first_pass=first_log["chance"][d], included=d in kept,
                             final_score=fin["score"].get(d, np.nan), reason="" if d in kept else
                             f"점수 {first_log['score'][d]:.2f} < {M_MIN} 또는 우연+{M_MARGIN} 미달(제외 순서 반복 후)"))
    h = {c: float(np.median([match(R[HOLIDAY], R[o]) for o in cand])) for c, cand in (("weekday", wd), ("weekend", we))}
    rows.append(dict(date=HOLIDAY, cls="holiday(참고)", trains_06_22=int(sum(len(v) for v in R[HOLIDAY].values())),
                     score_first_pass=np.nan, included=False, reason=f"그룹 편입 안 함; 평일 그룹 중앙 M={h['weekday']:.3f}, 주말 그룹 중앙 M={h['weekend']:.3f}"))
    cross = float(np.median([match(R[a], R[b]) for a in wd for b in we]))
    pd.DataFrame(rows).to_csv(OUT / "day_check.csv", index=False, float_format="%.4f")
    res["day_check"] = dict(weekday_group=wd, weekend_group=we, holiday_median_M=h, weekday_weekend_cross_median_M=cross,
                            pairwise_weekday=pd.DataFrame([[match(R[a], R[b]) if a != b else np.nan for b in WEEKDAYS] for a in WEEKDAYS], index=WEEKDAYS, columns=WEEKDAYS).round(3).to_dict())
    print("day check", wd, we, h, cross, flush=True)

    events, lag_tables, fig = [], [], {}
    # ---- 1/08 single-day baselines ----
    a08 = DF[dstr(8)]
    _, tabs08, info08, fr08 = fit_tables(a08, active, refine=False)
    ps08 = PaxSet(a08, active)
    L30 = const_lags(tabs08)
    res["i_old_a_0108_lag30_0"] = eval_group(tabs08, ps08, active, *L30)["all"]
    Lo, Li, lt = fit_lags(tabs08, ps08, active)
    res["ii_single0108_fitted_lags"] = eval_group(tabs08, ps08, active, Lo, Li)["all"]
    lt.insert(0, "group", "single_0108"); lag_tables.append(lt)
    res["single0108"] = dict(trains=fr08["trains"], both_ends=fr08["both_ends_within_2"], median_obs=fr08["median_obs"],
                             median_strength=float(np.median(np.r_[info08[f"toward_{first}"]["strength"], info08[f"toward_{last}"]["strength"]])),
                             peaks=sum(i["peaks"] for i in info08.values()))

    for gname, days in (("weekday", wd), ("weekend", we)):
        if len(days) < 3:
            res[gname] = "not built (<3 days)"
            continue
        anchors = pd.concat([DF[d] for d in days], ignore_index=True)
        dayidx = np.concatenate([np.full(len(DF[d]), i) for i, d in enumerate(days)])
        dirs, tabs, info, fr = fit_tables(anchors, active, refine=True)
        ps = PaxSet(anchors, active, dayidx)
        r = dict(days=days, anchors=len(anchors), trains=fr["trains"], both_ends=fr["both_ends_within_2"], small=fr["small_1_2_observed"],
                 median_obs=fr["median_obs"], median_strength=float(np.median(np.r_[info[f"toward_{first}"]["strength"], info[f"toward_{last}"]["strength"]])),
                 peaks=sum(i["peaks"] for i in info.values()), moved_trains={k: v["moved"] for k, v in info.items()},
                 order_violations={k: v["order_violations"] for k, v in info.items()})
        L30 = const_lags(tabs)
        r["iii_pooled_lag30_0"] = eval_group(tabs, ps, active, *L30, days=days)
        Lo, Li, lt = fit_lags(tabs, ps, active)
        r["iv_pooled_fitted_lags"] = eval_group(tabs, ps, active, Lo, Li, days=days)
        lt.insert(0, "group", gname); lag_tables.append(lt)
        # 1/08 inside this group
        if dstr(8) in days:
            i8 = days.index(dstr(8))
            m8 = ps.day == i8
            for key, (lo_, li_) in (("iii", L30), ("iv", (Lo, Li))):
                w, o, dmm = evaluate(tabs, ps, active, lo_, li_)
                r[f"{key}_on_0108"] = metrics(w, o, dmm, m8)
        # controls with refit lags on a 25% passenger sample
        idx_s = rng.choice(len(anchors), size=len(anchors) // 4, replace=False)
        idx_s.sort()
        ps_s = PaxSet(anchors.iloc[idx_s].reset_index(drop=True), active, dayidx[idx_s])
        ctrl = {}
        for nm, fn, reps in (("pooled_real", lambda t: t, 1), ("direction_swap", DC.swapped, 1), ("local_shuffle5", lambda t: DC.local_shuffle(t, rng), 3),
                             ("random_timetable", lambda t: DC.random_tt(t, rng), 3)):
            ms = []
            for _ in range(reps):
                tt = fn(tabs)
                lo_, li_, _ = fit_lags(tt, ps_s, active)
                ms.append(eval_group(tt, ps_s, active, lo_, li_)["all"])
            ctrl[nm] = {k: float(np.mean([m[k] for m in ms])) for k in ms[0]}
        r["controls_refit_lags_25pct_sample"] = ctrl
        res[gname] = r
        # holdout day diagnostic (weekday only)
        if gname == "weekday":
            hd = dstr(16) if dstr(16) in days else days[0]
            rest = [d for d in days if d != hd]
            anc_r = pd.concat([DF[d] for d in rest], ignore_index=True)
            _, tabs_r, info_r, fr_r = fit_tables(anc_r, active, refine=True)
            ps_r = PaxSet(anc_r, active)
            Lo_r, Li_r, _ = fit_lags(tabs_r, ps_r, active)
            ps_h = PaxSet(DF[hd], active)
            r["holdout_day"] = dict(day=hd, trains_without=fr_r["trains"],
                                    without_day_lag30_0=eval_group(tabs_r, ps_h, active, *const_lags(tabs_r))["all"],
                                    without_day_fitted=eval_group(tabs_r, ps_h, active, Lo_r, Li_r)["all"],
                                    with_day_fitted=r["iv_pooled_fitted_lags"][hd])
        # events
        for name, t in tabs.items():
            obs, tail = info[name]["obs"], info[name]["tail"]
            n = len(t["stations"])
            for i in range(len(t["arr"])):
                tid = f"C-{gname}-{name}-P{i + 1:04d}"
                for k, s in enumerate(t["stations"]):
                    sec = t["arr"][i, k]
                    events.append((gname, tid, name, int(s), f"{int(sec) // 3600:02d}:{int(sec) % 3600 // 60:02d}:{int(sec) % 60:02d}", bool(obs[i, k]),
                                   round(float(Lo[name][k]), 1), round(float(Li[name][k]), 1), bool(tail[i])))
        fig[gname] = dict(lag=lt.to_dict("list"))
        if gname == "weekday":
            fig["wait_hist"] = None
        print(gname, "done", flush=True)

    ev = pd.DataFrame(events, columns=["group", "train_id", "direction", "stationID", "arrival_time_of_day", "observed_peak_within_45s",
                                       "lag_out_s", "lag_in_s", "tail_unsupported_flag"])
    ev.to_csv(OUT / "candidate_arrival_events_pool.csv", index=False)
    pd.concat(lag_tables).to_csv(OUT / "lags_by_station.csv", index=False, float_format="%.2f")
    res["tail_unsupported"] = {g: float(x.drop_duplicates("train_id").tail_unsupported_flag.mean()) for g, x in ev.groupby("group")}
    (OUT / "pool_metrics.json").write_text(json.dumps(res, indent=1, default=float, ensure_ascii=False), encoding="utf-8")
    pd.DataFrame([{"date": d, **res["weekday"]["iv_pooled_fitted_lags"][d], **{"iii_" + k: v for k, v in res["weekday"]["iii_pooled_lag30_0"][d].items()}} for d in wd]).to_csv(
        OUT / "per_day_metrics_weekday.csv", index=False, float_format="%.4f")
    print(json.dumps({k: res[k] for k in res if k not in ("day_check",)}, indent=1, default=float, ensure_ascii=False)[:9000])


if __name__ == "__main__":
    main()
