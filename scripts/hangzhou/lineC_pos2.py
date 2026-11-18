"""lineC_pos2: new synthesis rule (E3/E2 centred, E1 reference only) re-evaluated on the planted short-turn scenarios; analysis zone; final timetable file.
Rules: outputs/hangzhou/lineC_pos2/criteria.md and outputs/hangzhou/lineC_final/criteria.md (frozen before running)."""
import json, pickle
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lineC_pool as P
import lineC_struct as S
from lineC_route_gate import build_topology, corridor_order, read_tags
import numpy as np
import pandas as pd

OUT = P.OUT.parent / "lineC_pos2"
FIN = P.OUT.parent / "lineC_final"
DAY, SEG, BANDS, EDGES = S.DAY, S.SEG, S.BANDS, S.EDGES
RUSH = (1, 3)


def setup():
    gate, trips, _ = read_tags()
    tracks, membership, _, _, _ = build_topology(gate)
    corridor = corridor_order(tracks["C"])
    active = [s for s in corridor if gate.get(s) == "C"]
    first, last = active[0], active[-1]
    pk = pickle.load(open(P.CACHE / "pool3_final.pkl", "rb"))
    tabs, Lo, days = pk["tabs"], pk["Lo"], pk["days"]
    n = len(active)
    DF = {d: P.load_day(d, first, last) for d in days}
    anchors = pd.concat([DF[d] for d in days], ignore_index=True)
    dayidx = np.concatenate([np.full(len(DF[d]), i) for i, d in enumerate(days)])
    ps = P.PaxSet(anchors, active, dayidx)
    dnames = [f"toward_{first}", f"toward_{last}"]
    order = {0: active[::-1], 1: active}
    Pp = P.prep(tabs)
    tr = np.full(ps.n, -1)
    for (di, x), idx in ps.gdx.items():
        lab = dnames[di]; t = Pp[lab]; k = t["col"][x]
        v = t["vals"][:, k] + Lo[lab][k]
        j = np.searchsorted(v, ps.X[idx], side="right") - 1
        gap = np.where(j >= 0, ps.X[idx] - v[np.clip(j, 0, None)], np.inf)
        tr[idx] = np.where(gap <= 600, t["order"][np.clip(j, 0, None), k], -1)
    posmap = {di: np.full(100, -1) for di in (0, 1)}
    for di in (0, 1):
        for k, s in enumerate(order[di]):
            posmap[di][s] = k
    posx = np.where(ps.d == 0, posmap[0][ps.x], posmap[1][ps.x])
    pose = np.where(ps.d == 0, posmap[0][ps.e], posmap[1][ps.e])
    ntr = {di: len(tabs[dnames[di]]["arr"]) for di in (0, 1)}
    bidx, ntrain = {}, {}
    for di in (0, 1):
        b = np.digitize(tabs[dnames[di]]["arr"][:, 0], EDGES) - 1
        bidx[di] = np.where((b >= 0) & (b < 5), b, -1)
        ntrain[di] = np.array([(bidx[di] == j).sum() for j in range(5)])
    return dict(active=active, tabs=tabs, Lo=Lo, days=days, n=n, ps=ps, dnames=dnames, order=order, tr=tr, posx=posx, pose=pose, ntr=ntr, bidx=bidx, ntrain=ntrain, DF=DF)


def Ncounts(c, keep, posx2):
    nd, n = len(c["days"]), c["n"]
    out = {}
    for di in (0, 1):
        m = keep & (c["ps"].d == di) & (c["tr"] >= 0)
        flat = (c["ps"].day[m] * c["ntr"][di] + c["tr"][m]) * n + posx2[m]
        out[di] = np.bincount(flat, minlength=nd * c["ntr"][di] * n).reshape(nd, c["ntr"][di], n).astype(float)
    return out


def e23(Nn, bidx, rng, nulls=2):
    nd, _, n = Nn[0].shape
    shp = (2, 5, 6)
    e2, e2n, pr, ab, typ_seg = (np.zeros(shp) for _ in range(5))
    for di in (0, 1):
        N = Nn[di]

        def repro(Nx):
            typ = np.full((N.shape[1], n), np.nan)
            for b in range(5):
                ix = bidx[di] == b
                if ix.any():
                    typ[ix] = Nx[:, ix, :].mean((0, 1))
            cand = (Nx >= 2.5 * typ[None]) & (typ[None] >= 8)
            for j in (1, 2, 3):
                tj = np.roll(typ, -j, axis=1)[None]
                cand &= (np.roll(Nx, -j, axis=2) <= 0.2 * tj) & (tj >= 8)
            cand[:, :, n - 5:] = False
            return cand.sum(0) >= 6
        rep = repro(N)
        nl = []
        for _ in range(nulls):
            Nx = N.copy()
            for b in range(5):
                ix = np.flatnonzero(bidx[di] == b)
                if len(ix) < 2:
                    continue
                for i in range(nd):
                    for k in range(n):
                        Nx[i, ix, k] = N[i, rng.permutation(ix), k]
            nl.append(repro(Nx))
        tot = N.sum(0)
        for b in range(5):
            ix = np.flatnonzero(bidx[di] == b)
            if len(ix) == 0:
                continue
            obs = np.column_stack([tot[ix][:, a:z].sum(1) for a, z in SEG])
            typg = obs.mean(0)
            present = (obs >= 0.5 * typg) & (obs >= 30)
            absent = (obs <= 0.1 * typg) & (typg >= 100)
            for g, (a, z) in enumerate(SEG):
                e2[di, b, g] = rep[ix][:, a:z].any(1).mean()
                e2n[di, b, g] = np.mean([m[ix][:, a:z].any(1).mean() for m in nl])
                pr[di, b, g] = present[:, g].mean(); ab[di, b, g] = absent[:, g].mean(); typ_seg[di, b, g] = typg[g]
    return e2, e2n, pr, ab, typ_seg


# ---- new synthesis rule (frozen in criteria.md) ----
E3_ABS, E2_MIN, PRES, TYP_MIN = 0.15, 0.05, 0.85, 100


def verdicts2(e2, e2n, pr, ab, typ, zone):
    V = np.empty((2, 5, 6), object)
    for di in (0, 1):
        for b in range(5):
            for g in range(6):
                if not zone[di, b]:
                    V[di, b, g] = "미확인"; continue
                def e2s(gg):
                    return gg >= 0 and e2[di, b, gg] >= E2_MIN and e2[di, b, gg] >= 2 * e2n[di, b, gg]
                inform = typ[di, b, g] >= TYP_MIN
                sup = inform and (ab[di, b, g] >= E3_ABS) or e2s(g) or e2s(g - 1)
                ref = inform and pr[di, b, g] >= PRES and ab[di, b, g] < E3_ABS
                V[di, b, g] = "지원" if sup else "반박" if ref else "알 수 없음"
    return V
