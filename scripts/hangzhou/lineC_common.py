"""Shared helpers for the line-C pipeline (A/B/C labels only; 'probably Line x' lives in the brief, not in code).
Single process, threads=1, BELOW_NORMAL. Positions come from the ID-order hypothesis; B's side branch (ids 28-33 hanging off id 20) is
handled in B leg distances because the user supplied the line map (docs/AI/HANGZHOU_TIMETABLE_BRIEF.md section 7)."""
import os
for v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[v] = "1"
import ctypes, json
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs/hangzhou/lineC"
CACHE = ROOT / "outputs/hangzhou/cache"
OUT.mkdir(parents=True, exist_ok=True)
try:
    ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
except Exception:
    pass
STP = pd.read_csv(ROOT / "outputs/hangzhou/stageB0/station_positions.csv")          # built from 2019-01-08, frozen
POS = {L: dict(zip(g.stationID, g.pos)) for L, g in STP.groupby("line")}
ID_OF = {L: g.sort_values("pos").stationID.to_numpy() for L, g in STP.groupby("line")}
NC = len(ID_OF["C"])                       # 32 stations, positions 0..31
MODELS = json.load(open(CACHE / "same_line_models.json"))["models"]   # fitted on 2019-01-08, frozen
HUB = {"B": dict(X_id=10, C_id=51), "A": dict(X_id=77, C_id=46)}      # fixed interchange hubs (B10-C51, A77-C46)


def cfun(L, dd):
    m = MODELS[L]; d, mono = np.array(m["d"]), np.array(m["mono"])
    slope = (mono[-1] - mono[-4]) / (d[-1] - d[-4])
    out = np.where(dd <= d[-1], np.interp(dd, d, mono), mono[-1] + slope * (dd - d[-1]))
    return np.maximum(0.0, np.where(dd == 0, m["a"], out) - m["a"])


def b_dist(id1, id2, branch=True):
    """number of stations between two B stations; ids 28-33 hang off id 20 when branch=True (user-supplied line map)."""
    id1, id2 = np.asarray(id1), np.asarray(id2)
    if not branch:
        return np.abs(id1 - id2)
    br1, br2 = id1 >= 28, id2 >= 28
    same = br1 == br2
    d_same = np.abs(id1 - id2)
    d_x = np.where(br1, (id1 - 27) + np.abs(20 - id2), (id2 - 27) + np.abs(20 - id1))
    return np.where(same, d_same, d_x)


def load_day(date):
    """returns (d sorted by user/time with prev-record columns, trips)."""
    d = pd.read_csv(ROOT / f"data/external/hangzhou/record_{date}.csv", usecols=["time", "lineID", "stationID", "status", "userID", "payType"], parse_dates=["time"])
    d["t"] = (d.time - pd.Timestamp(date)).dt.total_seconds().astype("int64")
    d = d.sort_values(["userID", "t", "status"], kind="stable").reset_index(drop=True)
    same = d.userID.eq(d.userID.shift(1))
    for c in ("t", "lineID", "stationID", "status"):
        d["p_" + c] = d[c].shift(1).where(same)
    ex = d[(d.status == 0)].copy()
    ex["paired"] = (ex.p_status == 1) & ((ex.t - ex.p_t) <= 180 * 60)
    return d.drop(columns=["time"]), ex
