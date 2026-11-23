"""E-40: does each method rank the known real peak (hour / train / station) in the top 1-3? Criteria: outputs/diagnostics/peak_rank_check/criteria.md.
Validation only; nothing is tuned or written to production."""
import hashlib, json, sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import numpy as np, pandas as pd, joblib
from scipy.stats import rankdata
sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_ground_truth as gt
import gt_train_od as od

ROOT = gt.ROOT
OUT = ROOT / "outputs/diagnostics/peak_rank_check"
ADAM_SHA = "8a7c1822c2bd2d5cb9d583bd24a390391728b46ee7b74b4d7b7ce9b1484ad5f6"
EXCLUDE_EXTRA = {"2026-08-21"}  # 2m20s start->arrival, see criteria.md
COLS = ["train_id", "direction", "station", "hour", "load"]


def day_job(date):
    P = od.build_problem(date)
    x, _ = od.fit(P, od.base_q(P, "uniform", None, 1.0), 0.01)
    fo = od.to_frame(P, x)[COLS]
    ev = P["ev"]; cell = P["cell"]
    b = np.where(ev.is_destination == 0, P["B"][cell] / np.maximum(P["elig_b"][cell], 1), 0.0)
    a = np.where(ev.is_origin == 0, P["A"][cell] / np.maximum(P["elig_a"][cell], 1), 0.0)
    nv = ev.copy(); nv["load"] = 0.0
    for s, e in P["slices"]:
        c = 0.0
        for i in range(s, e):
            c = max(c + b[i] - a[i], 0.0); nv.iat[i, nv.columns.get_loc("load")] = c
    return date, fo, nv[COLS]


def rank_stats(scores, true_key, ks=(1, 3)):
    """scores: Series indexed by item. Rank 1 = highest. Returns avg rank, fractional hit@k, n."""
    s = scores.round(6); n = len(s)
    r = rankdata(-s.to_numpy(), method="average"); t = r[list(s.index).index(true_key)]
    m = int((s == s[true_key]).sum()); lo = t - (m - 1) / 2   # best rank in tie group
    return dict(rank=t, n=n, **{f"hit{k}": float(np.clip((k - lo + 1) / m, 0, 1)) for k in ks})


def hgb_hour_scores(model, date, station, dcode):
    day_type = gt.get_day_type(date); rows = []
    nxt = (pd.Timestamp(date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    w = {d: json.loads((gt.WEATHER_DIR / f"{d}.json").read_text(encoding="utf-8"))["hourly"] for d in (date, nxt)}
    out = {}
    for h in gt.HOURS:
        d = nxt if h == 24 else date; hh = w[d]; i = hh["time"].index(f"{d}T{0 if h == 24 else h:02d}:00")
        out[h] = dict(station_idx=gt.STATION_TO_IDX[station], hour=h, dir_code=dcode, is_weekend=int(day_type == "휴일"),
                      temp=hh["temperature_2m"][i], precip=hh["precipitation"][i], snow=hh["snowfall"][i],
                      plan_version=int(date >= gt.PLAN_CHANGE_DATE))
    X = pd.DataFrame(out.values())[list(model.feature_names_in_)]
    return pd.Series(model.predict(X), index=list(out))


def main():
    sha = hashlib.sha256((ROOT / "outputs/ground_truth_train_loads.csv").read_bytes()).hexdigest()
    sha_ok = sha == ADAM_SHA; print("adam csv sha ok:", sha_ok); assert sha_ok
    comp = pd.read_csv(ROOT / "outputs/peak_case_comparison.csv", encoding="utf-8-sig")
    comp = comp[comp.status == "matched"].reset_index(drop=True)
    dates = sorted(comp.service_date.unique())
    with ProcessPoolExecutor(3) as pool:
        res = {d: (fo, nv) for d, fo, nv in pool.map(day_job, dates)}
    adam = pd.read_csv(ROOT / "outputs/ground_truth_train_loads.csv", usecols=["date"] + COLS)
    adam = adam[adam.date.isin(dates)]
    model = joblib.load(ROOT / "outputs/load_predictor.joblib")
    rows = []
    for _, c in comp.iterrows():
        d, stn, dr, tid = c.service_date, c.peak_station, c.direction, c.synthetic_train_id
        fr = {"OD": res[d][0], "Adam": adam[adam.date == d][COLS], "Naive": res[d][1]}
        peak_hour = int(fr["OD"][(fr["OD"].train_id == tid) & (fr["OD"].station == stn)].hour.iloc[0])
        base = {k: f[(f.station == stn) & (f.direction == dr)] for k, f in fr.items()}
        hrs = sorted(base["OD"].hour.unique()); n_h = len(hrs)
        hgb = hgb_hour_scores(model, d, stn, int(dr == "하행")).loc[hrs]
        r = dict(date=d, excluded_extra=d in EXCLUDE_EXTRA, station=stn, dir=dr, peak_train=tid, peak_hour=peak_hour, n_hours=n_h)
        # primary: hour rank
        sc = {k: b.groupby("hour").load.mean() for k, b in base.items()}; sc["HGB"] = hgb
        for k, s in sc.items():
            st = rank_stats(s, peak_hour); r.update({f"{k}_hr_rank": st["rank"], f"{k}_hr_h1": st["hit1"], f"{k}_hr_h3": st["hit3"]})
        r.update(Rand_hr_rank=(n_h + 1) / 2, Rand_hr_h1=1 / n_h, Rand_hr_h3=min(3, n_h) / n_h)
        # secondary 1: train rank at that station/direction
        hour_of = base["OD"].set_index("train_id").hour; n_t = len(hour_of)
        for k in ("OD", "Adam", "Naive"):
            s = base[k].set_index("train_id").load; st = rank_stats(s, tid); r.update({f"{k}_tr_rank": st["rank"], f"{k}_tr_h1": st["hit1"], f"{k}_tr_h3": st["hit3"]})
        s = hour_of.map(hgb); st = rank_stats(s, tid); r.update(HGB_tr_rank=st["rank"], HGB_tr_h1=st["hit1"], HGB_tr_h3=st["hit3"])
        r.update(n_trains=n_t, Rand_tr_rank=(n_t + 1) / 2, Rand_tr_h1=1 / n_t, Rand_tr_h3=min(3, n_t) / n_t)
        # secondary 2: station rank within the peak hour/direction
        for k in ("OD", "Adam", "Naive"):
            f = fr[k]; f = f[(f.direction == dr) & (f.hour == peak_hour)]
            st = rank_stats(f.groupby("station").load.mean(), stn); r.update({f"{k}_st_rank": st["rank"], f"{k}_st_h1": st["hit1"], f"{k}_st_h3": st["hit3"]}); n_s = st["n"]
        hs = pd.Series({s_: hgb_hour_scores(model, d, s_, int(dr == "하행"))[peak_hour] for s_ in f.station.unique()})
        st = rank_stats(hs, stn); r.update(HGB_st_rank=st["rank"], HGB_st_h1=st["hit1"], HGB_st_h3=st["hit3"])
        r.update(n_stations=n_s, Rand_st_rank=(n_s + 1) / 2, Rand_st_h1=1 / n_s, Rand_st_h3=min(3, n_s) / n_s)
        rows.append(r)
    df = pd.DataFrame(rows); df.to_csv(OUT / "per_case.csv", index=False, encoding="utf-8-sig")
    M = ["OD", "Adam", "Naive", "HGB", "Rand"]; summ = {}
    for label, sub in (("N18_primary", df[~df.excluded_extra]), ("N19_sensitivity", df)):
        summ[label] = {lv: {m: dict(mean_rank=float(sub[f"{m}_{lv}_rank"].mean()), hit1=float(sub[f"{m}_{lv}_h1"].mean()),
                                    hit3=float(sub[f"{m}_{lv}_h3"].mean())) for m in M if f"{m}_{lv}_rank" in sub}
                       for lv in ("hr", "tr", "st")}
        summ[label]["n"] = len(sub)
    p = summ["N18_primary"]["hr"]
    c1 = p["OD"]["hit3"] >= 0.5
    c2 = all(p["OD"]["hit3"] - p[m]["hit3"] >= 0.15 for m in ("Adam", "Naive"))
    c3 = all(p[m]["mean_rank"] - p["OD"]["mean_rank"] >= 1.0 for m in ("Adam", "Naive"))
    summ["criteria"] = dict(c1_hit3_ge_0_5=bool(c1), c2_margin_hit3_0_15=bool(c2), c3_margin_rank_1_0=bool(c3), all_met=bool(c1 and c2 and c3))
    summ["adam_csv_sha256_ok"] = sha_ok
    (OUT / "summary.json").write_text(json.dumps(summ, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summ, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
