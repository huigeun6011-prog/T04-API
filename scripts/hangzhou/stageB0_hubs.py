"""Stage B0 steps 2-6: interchange (hub) inference for cross-line trips, 2019-01-08 ONLY. Run after stageB0_prepare.py.
ASSUMPTIONS (flagged): station position = rank of stationID in its line block (ID-order hypothesis); one constant walk+wait W per hub (fitted);
 no branches resolved; hubs are (station on line X, station on line Y) pairs since each line has its own IDs.
DECLARED BEFORE RESULTS (not changed afterwards):
 model: total minutes = c_X(|pX - hx|) + c_Y(|pY - hy|) + W,  c_L from stageB0_prepare (q25-based, intercept removed). Unordered line pair, both directions pooled.
 candidate score = mean |residual - W_cand|, W_cand = median residual (L1-optimal). Search = all (hx, hy) on a seeded 20,000-trip sample (final stats on all trips).
 identifiability class per line pair: 'clear' if best candidate beats the best candidate that differs by >1 station on either line by >= 0.5 min of mean |res|;
   else 'ambiguous'. Also report top-5 and whether they lie within +-1 station of the best.
 hubs: greedy forward selection of up to 3 hubs (each with its own W); a further hub is 'supported' if it lowers the mean |res| by >= 10% on the HELD-OUT half of users.
 trip assignment: to the selected hub with smallest |res|; 'unambiguous' if only one hub is selected or the 2nd-best selected hub is >= 3 min worse in |res|.
 'splittable' trip: |res| <= 5 min with its assigned hub AND unambiguous.
 hold-out: random half of USERS (seed 20190108): fit on one half, evaluate on the other; agreement = same top-1 hub within +-1 station on both lines, and share of per-trip same assignments.
 weak check (labelled weak): taps per day at the hub station divided by the median of its +-3 neighbours on the same line.
 via-third-line check: A<->C trips, direct (best single hub, searched) vs via B using the best A-B and B-C hubs (+ one constant W); compare mean |res|."""
import os
for v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[v] = "1"
import ctypes, json
from pathlib import Path
import numpy as np, pandas as pd
try:
    ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
except Exception:
    pass
ROOT = Path(__file__).resolve().parents[2]
OUT, CACHE = ROOT / "outputs/hangzhou/stageB0", ROOT / "outputs/hangzhou/cache"
tr = pd.read_pickle(CACHE / "trips_2019-01-08.pkl"); mods = json.load(open(CACHE / "same_line_models.json"))["models"]
stp = pd.read_csv(OUT / "station_positions.csv")
pos2id = {L: g.sort_values("pos").stationID.to_numpy() for L, g in stp.groupby("line")}
NPOS = {L: len(v) for L, v in pos2id.items()}


def cfun(L, dd):
    m = mods[L]; d, mono = np.array(m["d"]), np.array(m["mono"])
    slope = (mono[-1] - mono[-4]) / (d[-1] - d[-4])
    out = np.where(dd <= d[-1], np.interp(dd, d, mono), mono[-1] + slope * (dd - d[-1]))
    return np.maximum(0.0, np.where(dd == 0, m["a"], out) - m["a"])


def side(df, X, Y):
    a = (df.entry_line == X) & (df.exit_line == Y); b = (df.entry_line == Y) & (df.exit_line == X)
    d = df[a | b].copy()
    d["pX"] = np.where(d.entry_line == X, d.entry_pos, d.exit_pos).astype(int); d["pY"] = np.where(d.entry_line == Y, d.entry_pos, d.exit_pos).astype(int)
    d["fwd"] = d.entry_line == X
    return d


def resid_matrix(d, X, Y):
    cx = np.stack([cfun(X, np.abs(d.pX.to_numpy() - h)) for h in range(NPOS[X])], 1)
    cy = np.stack([cfun(Y, np.abs(d.pY.to_numpy() - h)) for h in range(NPOS[Y])], 1)
    return (d.minutes.to_numpy()[:, None, None] - cx[:, :, None] - cy[:, None, :]).astype(np.float32)


def score_all(R):
    W = np.median(R, axis=0)
    A = np.abs(R - W[None]); return A.mean(0), W, A


def run_pair(d_all, X, Y, rng, n=20000):
    d = d_all.sample(min(n, len(d_all)), random_state=int(rng.integers(1 << 30)))
    S, W, A = score_all(resid_matrix(d, X, Y))
    order = np.dstack(np.unravel_index(np.argsort(S, axis=None), S.shape))[0]
    return d, S, W, A, order


def greedy(A, S, k=3):
    nY = S.shape[1]; Af = A.reshape(len(A), -1); sel = []; cur = np.full(len(A), np.inf); hist = []
    for _ in range(k):
        sc = np.minimum(cur[:, None], Af).mean(0); j = int(np.argmin(sc)); sel.append(j); cur = np.minimum(cur, Af[:, j]); hist.append(float(cur.mean()))
    return [divmod(j, nY) for j in sel], hist


def eval_hubs(d, X, Y, hubs, Ws):
    cols = [np.abs(d.minutes.to_numpy() - cfun(X, np.abs(d.pX.to_numpy() - hx)) - cfun(Y, np.abs(d.pY.to_numpy() - hy)) - w) for (hx, hy), w in zip(hubs, Ws)]
    M = np.stack(cols, 1); idx = M.argmin(1); best = M.min(1)
    gap = np.sort(M, 1)[:, 1] - best if M.shape[1] > 1 else np.full(len(M), np.inf)
    return best, idx, gap


rng = np.random.default_rng(20190108)
cross = tr[tr.entry_line != tr.exit_line]
users = cross.userID.unique(); half = set(rng.choice(users, len(users) // 2, replace=False))
rows, top_rows, ident_rows, hub_rows, hold_rows, geo_rows, weak_rows, fitted = [], [], [], [], [], [], [], {}
taps = pd.read_pickle(CACHE / "station_taps_B0.pkl"); taps["tot"] = taps.entries + taps.exits
for X, Y in (("A", "B"), ("A", "C"), ("B", "C")):
    d_all = side(cross, X, Y); nm = f"{X}{Y}"
    d, S, W, A, order = run_pair(d_all, X, Y, rng)
    b = tuple(order[0]); nonnb = next(o for o in order if abs(o[0] - b[0]) > 1 or abs(o[1] - b[1]) > 1)
    for r, o in enumerate(order[:5]):
        top_rows.append(dict(pair=nm, rank=r + 1, hubX_id=int(pos2id[X][o[0]]), hubY_id=int(pos2id[Y][o[1]]), posX=int(o[0]), posY=int(o[1]), mean_abs_res=round(float(S[o[0], o[1]]), 3),
                             W_min=round(float(W[o[0], o[1]]), 2), within_1_of_best=bool(abs(o[0] - b[0]) <= 1 and abs(o[1] - b[1]) <= 1)))
    gap = float(S[nonnb[0], nonnb[1]] - S[b])
    ident_rows.append(dict(pair=nm, n_trips=len(d_all), best_score=round(float(S[b]), 3), best_nonneighbour=f"posX{nonnb[0]}-posY{nonnb[1]}", gap_to_nonneighbour_min=round(gap, 3),
                           cls="clear" if gap >= 0.5 else "ambiguous", flat_median_score=round(float(np.median(S)), 3)))
    hubs, hist = greedy(A, S, 3); Ws = [float(W[h]) for h in hubs]
    for k in (1, 2, 3):
        best, idx, gp = eval_hubs(d_all, X, Y, hubs[:k], Ws[:k])
        unamb = (gp >= 3) | (k == 1)
        hub_rows.append(dict(pair=nm, n_hubs=k, hubs="; ".join(f"X{pos2id[X][h[0]]}-Y{pos2id[Y][h[1]]}(W={w:.1f})" for h, w in zip(hubs[:k], Ws[:k])),
                             mean_abs_res=round(float(best.mean()), 3), median_abs_res=round(float(np.median(best)), 3), p25=round(float(np.quantile(best, .25)), 3), p75=round(float(np.quantile(best, .75)), 3),
                             share_within_5=round(float((best <= 5).mean()), 4), unambiguous_share=round(float(unamb.mean()), 4), splittable_share=round(float(((best <= 5) & unamb).mean()), 4),
                             assign_shares=str(np.round(np.bincount(idx, minlength=k) / len(idx), 3).tolist())))
    fitted[nm] = dict(hubs=hubs, Ws=Ws)
    best, idx, gp = eval_hubs(d_all, X, Y, hubs[:2], Ws[:2])
    for k, (hx, hy) in enumerate(hubs[:2]):
        sub = d_all[idx == k]
        geo_rows.append(dict(pair=nm, hub=k + 1, hubX_id=int(pos2id[X][hx]), hubY_id=int(pos2id[Y][hy]), n=int(len(sub)),
                             X_below=round(float((sub.pX < hx).mean()), 3), X_at=round(float((sub.pX == hx).mean()), 3), X_above=round(float((sub.pX > hx).mean()), 3),
                             Y_below=round(float((sub.pY < hy).mean()), 3), Y_at=round(float((sub.pY == hy).mean()), 3), Y_above=round(float((sub.pY > hy).mean()), 3),
                             pX_minus_hub_q10_50_90=str(np.quantile(sub.pX - hx, [.1, .5, .9]).tolist()), pY_minus_hub_q10_50_90=str(np.quantile(sub.pY - hy, [.1, .5, .9]).tolist()),
                             hubX_pos=f"{hx}/{NPOS[X] - 1}", hubY_pos=f"{hy}/{NPOS[Y] - 1}"))
    inA = d_all.userID.isin(half); da, db = d_all[inA], d_all[~inA]; fits = []
    for part in (da, db):
        dp, Sp, Wp, Ap, ordp = run_pair(part, X, Y, np.random.default_rng(7))
        hp, _ = greedy(Ap, Sp, 2); fits.append((hp, [float(Wp[h]) for h in hp], tuple(ordp[0])))
    (hpa, wpa, ba), (hpb, wpb, bb) = fits
    ra, _, _ = eval_hubs(db, X, Y, hpa[:1], wpa[:1]); rb, _, _ = eval_hubs(db, X, Y, hpb[:1], wpb[:1])
    ra2, ia2, _ = eval_hubs(db, X, Y, hpa[:2], wpa[:2]); _, ib2, _ = eval_hubs(db, X, Y, hpb[:2], wpb[:2])
    ca, cb = np.array([hpa[i] for i in ia2]), np.array([hpb[i] for i in ib2])
    hold_rows.append(dict(pair=nm, top1_half_A=f"posX{ba[0]}-posY{ba[1]}", top1_half_B=f"posX{bb[0]}-posY{bb[1]}", top1_agree_within_1=bool(abs(ba[0] - bb[0]) <= 1 and abs(ba[1] - bb[1]) <= 1),
                          heldout_1hub_A_on_B=round(float(ra.mean()), 3), insample_1hub_B_on_B=round(float(rb.mean()), 3), heldout_2hub_A_on_B=round(float(ra2.mean()), 3),
                          second_hub_improvement_heldout=round(float(1 - ra2.mean() / ra.mean()), 4), second_hub_supported=bool(1 - ra2.mean() / ra.mean() >= 0.10),
                          per_trip_assignment_agreement_within1=round(float((np.abs(ca - cb) <= 1).all(1).mean()), 4), halfA_hubs=str(hpa), halfB_hubs=str(hpb)))
    for L, hp in ((X, hubs[0][0]), (Y, hubs[0][1])):
        ids = pos2id[L]; nb = [ids[j] for j in range(max(0, hp - 3), min(len(ids), hp + 4)) if j != hp]
        weak_rows.append(dict(pair=nm, hub=1, line=L, station_id=int(ids[hp]), taps_day=int(taps.tot[ids[hp]]), neighbour_median=float(taps.tot[nb].median()),
                              ratio=round(float(taps.tot[ids[hp]] / taps.tot[nb].median()), 2), line_percentile_of_taps=round(float((taps.tot[ids] <= taps.tot[ids[hp]]).mean()), 2)))
    for fw, g in d_all.groupby("fwd"):
        b1, _, _ = eval_hubs(g, X, Y, hubs[:1], Ws[:1])
        rows.append(dict(pair=nm, direction=f"{X}->{Y}" if fw else f"{Y}->{X}", n=len(g), median_abs_res_best_hub=round(float(np.median(b1)), 3), share_within_5=round(float((b1 <= 5).mean()), 4)))
for name, r in (("top5_candidates_per_pair", top_rows), ("identifiability", ident_rows), ("hubs_per_pair", hub_rows), ("holdout_agreement", hold_rows),
                ("hub_geometry", geo_rows), ("weak_check_taps_ratio", weak_rows), ("direction_consistency", rows)):
    pd.DataFrame(r).to_csv(OUT / f"{name}.csv", index=False)
json.dump({k: dict(hubs=[list(map(int, h)) for h in v["hubs"]], Ws=v["Ws"]) for k, v in fitted.items()}, open(CACHE / "hubs_B0.json", "w"))
# ---- step 6: A<->C direct vs via B
ac = side(cross, "A", "C"); sample = ac.sample(min(20000, len(ac)), random_state=3)
Rd = resid_matrix(sample, "A", "C"); Sd, Wd, _ = score_all(Rd); bd = np.unravel_index(np.argmin(Sd), Sd.shape)
direct_res = np.abs(Rd[:, bd[0], bd[1]] - Wd[bd])
hA, hB1 = fitted["AB"]["hubs"][0]; hB2, hC = fitted["BC"]["hubs"][0]
rv = sample.minutes.to_numpy() - cfun("A", np.abs(sample.pX.to_numpy() - hA)) - cfun("B", np.full(len(sample), abs(hB1 - hB2))) - cfun("C", np.abs(sample.pY.to_numpy() - hC))
Wv = float(np.median(rv)); via_abs = np.abs(rv - Wv)
res6 = dict(n=len(sample), direct_best=f"A id {pos2id['A'][bd[0]]} - C id {pos2id['C'][bd[1]]}", direct_mean_abs=float(direct_res.mean()), direct_W=float(Wd[bd]),
            via_B_hubs=f"A{pos2id['A'][hA]} -> B{pos2id['B'][hB1]} ... B{pos2id['B'][hB2]} -> C{pos2id['C'][hC]}", via_mean_abs=float(via_abs.mean()), via_W_total=Wv,
            share_via_better_by_3min=float((via_abs + 3 < direct_res).mean()), share_direct_better_by_3min=float((direct_res + 3 < via_abs).mean()), via_B_leg_stations=abs(hB1 - hB2),
            note="direct = 1088-candidate search, via = fixed hubs from AB/BC fits + one W (no search)")
(OUT / "via_third_line_check.json").write_text(json.dumps(res6, indent=1, default=float), encoding="utf-8")
pd.set_option("display.width", 250)
for name in ("identifiability", "hubs_per_pair", "top5_candidates_per_pair", "holdout_agreement", "hub_geometry", "weak_check_taps_ratio", "direction_consistency"):
    print(name); print(pd.read_csv(OUT / f"{name}.csv").drop(columns=[c for c in ("halfA_hubs", "halfB_hubs") if c in pd.read_csv(OUT / f"{name}.csv").columns]).to_string())
print(json.dumps(res6, indent=1, default=float))
