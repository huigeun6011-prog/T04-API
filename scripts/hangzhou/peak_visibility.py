"""The Stage A detector and visibility classes, without file I/O."""

import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks


def analyse(times, lo, hi):
    n = hi - lo
    h = np.bincount(times[(times >= lo) & (times < hi)] - lo, minlength=n).astype(float)
    tot = h.sum()
    out = dict(exits_window=int(tot), n_peaks=0, median_interval_s=np.nan, regularity=np.nan,
               explained=np.nan, coverage=np.nan, lift=np.nan)
    if tot < 30:
        return out | dict(cls="none")
    sm = gaussian_filter1d(h, 10)
    pk, _ = find_peaks(sm, distance=45, height=sm.mean() * 2.5)
    out["n_peaks"] = len(pk)
    hours = n / 3600
    if len(pk) >= 2:
        iv = np.diff(pk)
        out["median_interval_s"] = float(np.median(iv))
        out["regularity"] = float((np.quantile(iv, .75) - np.quantile(iv, .25)) / np.median(iv))
    if len(pk):
        m = np.zeros(n, bool)
        for p in pk:
            m[max(0, p - 45):p + 46] = True
        out["explained"] = float(h[m].sum() / tot)
        out["coverage"] = float(m.mean())
        out["lift"] = out["explained"] / out["coverage"]
    clear = (len(pk) >= 2 and len(pk) >= 3.3 * hours and out["explained"] >= .40
             and out["lift"] >= 1.8 and out["regularity"] <= .6)
    weak = len(pk) >= .83 * hours and out["explained"] >= .15
    return out | dict(cls="clear" if clear else "weak" if weak else "none")
