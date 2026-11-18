"""항저우 C선 정답 재차인원 생성기 (직접 통행 승객 -> 시간표 열차 배정). 기준: outputs/hangzhou/od_test/criteria.md.
정답은 '추정 시간표 위의 정답'이다. 원본 태그(data/external)는 읽기만 한다."""
import os
for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_v] = "1"
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/external/hangzhou"
OUT = ROOT / "outputs/hangzhou/od_test"
CACHE = ROOT / "outputs/hangzhou/cache"          # gitignore
TT_PATH = ROOT / "outputs/hangzhou/lineC_final/candidate_arrival_events_final.csv"
DWELL, MAXGAP, WIN_HI = 30, 600, 600
H0, H1 = 5, 23
NH = H1 - H0 + 1


def low_priority():
    try:
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
    except Exception:
        pass


class Timetable:
    """최종 평일 시간표. 방향 코드 1 = toward_66(역 번호 증가), 0 = toward_34."""

    def __init__(self, path=TT_PATH):
        t = pd.read_csv(path)
        t["time_s"] = pd.to_timedelta(t.arrival_time).dt.total_seconds()
        ids = sorted(t.stationID.unique())
        self.ids = ids
        self.NS = len(ids)
        sidx = {s: i for i, s in enumerate(ids)}
        t["station_idx"] = t.stationID.map(sidx)
        t["dir_code"] = (t.direction == "toward_66").astype(int)
        g = t.groupby("train_id", sort=False)
        names = list(g.groups.keys())
        self.K = len(names)
        n = self.NS
        assert (g.size() == n).all()
        t["train_idx"] = np.repeat(np.arange(self.K), n)
        t["pos"] = np.tile(np.arange(n), self.K)
        # 행 순서 점검: 이동 방향 순서, 시각 증가
        sidx_mat = t.station_idx.to_numpy().reshape(self.K, n)
        dirs = t.dir_code.to_numpy().reshape(self.K, n)[:, 0]
        up = np.arange(n)
        assert all((sidx_mat[k] == (up if dirs[k] == 1 else up[::-1])).all() for k in range(self.K))
        tm = t.time_s.to_numpy().reshape(self.K, n)
        assert (np.diff(tm, axis=1) > 0).all()
        t["hour"] = (t.time_s // 3600).astype(int)
        assert t.hour.between(H0, H1).all()
        t["hour_idx"] = t.hour - H0
        t["is_origin"] = (t.pos == 0).astype(int)
        t["is_destination"] = (t.pos == n - 1).astype(int)
        t["imputed_train"] = t.groupby("train_idx").imputed.transform("max").astype(bool)
        t["low_signal_train"] = t.groupby("train_idx").low_signal.transform(lambda s: s.astype(str).str.lower().eq("true").any()).astype(bool)
        self.ev = t[["train_idx", "train_id", "direction", "dir_code", "stationID", "station_idx", "pos", "time_s", "hour", "hour_idx",
                     "is_origin", "is_destination", "imputed_train", "low_signal_train", "lag_out_s", "lag_in_s"]].reset_index(drop=True)
        self.slices = [(k * n, (k + 1) * n) for k in range(self.K)]
        self.dircode = dirs
        self.ARR = np.zeros((self.K, n))                        # 역 번호 순서(station_idx) 열
        self.ARR[np.arange(self.K)[:, None], sidx_mat] = tm
        self.LOUT = np.zeros((2, n)); self.LIN = np.zeros((2, n))
        for d in (0, 1):
            e = t[t.dir_code == d].drop_duplicates("station_idx").set_index("station_idx").sort_index()
            self.LOUT[d] = e.lag_out_s.to_numpy(); self.LIN[d] = e.lag_in_s.to_numpy()
        self.V = n * (n - 1) // 2


def read_pax(date, tt):
    """직접 통행(입·출장 모두 C, 같은 날 0<간격<=180분, 서로 다른 역). 결과를 캐시한다."""
    CACHE.mkdir(parents=True, exist_ok=True)
    cp = CACHE / f"od_test_pax_{date}.csv"
    if cp.exists():
        return pd.read_csv(cp)
    d = pd.read_csv(DATA / f"record_{date}.csv", usecols=["time", "lineID", "stationID", "status", "userID"],
                    dtype={"stationID": "int16", "lineID": "category", "status": "int8"}, parse_dates=["time"])
    d = d.sort_values(["userID", "time", "status"], kind="stable")
    dur = (d.time - d.time.shift()).dt.total_seconds() / 60
    sec = (d.time - pd.Timestamp(date)).dt.total_seconds().astype("int64")
    ex = d.status.eq(0)
    paired = ex & d.status.shift().eq(1) & d.userID.eq(d.userID.shift()) & dur.gt(0) & dur.le(180)
    p = pd.DataFrame({"e": d.stationID.shift()[paired].astype("int16"), "x": d.stationID[paired], "X": sec[paired], "E": sec.shift()[paired],
                      "line_e": d.lineID.shift()[paired].astype(str), "line_x": d.lineID[paired].astype(str)}).reset_index(drop=True)
    p = p[(p["line_e"] == "C") & (p["line_x"] == "C") & (p.e != p.x)].drop(columns=["line_e", "line_x"]).reset_index(drop=True)
    p = p[p.e.isin(tt.ids) & p.x.isin(tt.ids)].reset_index(drop=True)      # 시간표에 없는 역(54번 등)은 제외
    p.to_csv(cp, index=False)
    return p


def assign(pax, tt, lout_shift=0.0):
    """criteria.md의 배정 규칙. 반환: DataFrame(e_idx, x_idx, d, E, X, tr, ok)."""
    sidx = {s: i for i, s in enumerate(tt.ids)}
    ei = pax.e.map(sidx).to_numpy(); xi = pax.x.map(sidx).to_numpy()
    d = (xi > ei).astype(int)
    E, X = pax.E.to_numpy().astype(float), pax.X.to_numpy().astype(float)
    n = len(pax)
    tr = np.full(n, -1); ok = np.zeros(n, bool); wait = np.full(n, np.nan); gap = np.full(n, np.nan)
    for dc in (0, 1):
        trains = np.flatnonzero(tt.dircode == dc)
        for x in np.unique(xi[d == dc]):
            idx = np.flatnonzero((d == dc) & (xi == x))
            v = tt.ARR[trains, x] + tt.LOUT[dc, x] + lout_shift
            order = np.argsort(v, kind="stable"); vs = v[order]
            j = np.searchsorted(vs, X[idx], side="right") - 1
            jj = np.clip(j, 0, None)
            g = np.where(j >= 0, X[idx] - vs[jj], np.inf)
            good = g <= MAXGAP
            t_ = trains[order[jj]]
            D0 = tt.ARR[t_, ei[idx]] + DWELL - tt.LIN[dc, ei[idx]]
            w = D0 - E[idx]
            tr[idx] = np.where(good, t_, -1)
            wait[idx] = np.where(good, w, np.nan); gap[idx] = g
            ok[idx] = good & (w >= 0) & (w <= WIN_HI)
    hE, hX = (E // 3600).astype(int), (X // 3600).astype(int)
    hour_ok = (hE >= H0) & (hE <= H1) & (hX >= H0) & (hX <= H1)
    return pd.DataFrame(dict(e_idx=ei, x_idx=xi, d=d, E=E, X=X, tr=tr, wait=wait, gap=gap, assignable=(tr >= 0), window=ok, hour_ok=hour_ok, ok=ok & hour_ok))


def truth_from_assignment(a, tt):
    """정답 OD 벡터(열차 k, 승차 위치 a, 하차 위치 b 쌍 변수)와 시간별 승하차 합계 B, A(태그 시각의 시)."""
    n = tt.NS
    s = a[a.ok]
    pe = np.where(s.d == 1, s.e_idx, n - 1 - s.e_idx); px = np.where(s.d == 1, s.x_idx, n - 1 - s.x_idx)
    assert (px > pe).all()
    v = s.tr.to_numpy() * tt.V + pe * (2 * n - pe - 1) // 2 + px - pe - 1
    x_true = np.bincount(v, minlength=tt.K * tt.V).astype(float)
    hE, hX = (s.E // 3600).astype(int) - H0, (s.X // 3600).astype(int) - H0
    B = np.bincount(s.e_idx.to_numpy() * NH + hE.to_numpy(), minlength=n * NH).astype(float)
    A = np.bincount(s.x_idx.to_numpy() * NH + hX.to_numpy(), minlength=n * NH).astype(float)
    return x_true, B, A


def assignment_stats(a):
    return dict(n_direct_pax=int(len(a)), assignable=float(a.assignable.mean()), window=float(a.window.mean()), hour_ok=float(a.hour_ok.mean()),
                used=int(a.ok.sum()), used_share=float(a.ok.mean()),
                wait_neg_share_among_assignable=float((a.wait[a.assignable] < 0).mean()),
                wait_over_share_among_assignable=float((a.wait[a.assignable] > WIN_HI).mean()))
