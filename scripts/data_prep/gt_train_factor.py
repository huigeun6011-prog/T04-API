"""Per-train crowding factor w_k with x[k,a,b] = w_k * beta[cell(a)] * pi[a->b]  (SYNTHETIC recovery test only).
Event/cell conventions come from gt_train_od.build_problem (cell = station x stop-hour bucket, both directions together).
Real peak cases are never read here."""
import os
for v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[v] = "1"
import numpy as np
from scipy.optimize import minimize
import gt_train_od as od

NC = od.NC


def setup(date):
    P = od.build_problem(date)
    ev = P["ev"]
    P["K"] = len(P["slices"])
    P["tk"] = np.concatenate([np.full(e - s, k) for k, (s, e) in enumerate(P["slices"])])
    P["nd"] = (ev.is_destination == 0).to_numpy()
    first = np.array([ev.minute[s] for s, _ in P["slices"]], float)
    P["t0"] = first                                        # origin departure minute
    P["h0"] = (first // 60).astype(int)
    P["dir"] = np.array([ev.dir_code[s] for s, _ in P["slices"]])
    P["n_e"] = np.bincount(P["pa"], minlength=P["N"]).astype(float)
    return P


def pi_true(P, beta_d=0.1):
    d = (P["pb"] - P["pa"]).astype(float)
    attr = (P["A"][P["cell"][P["pb"]]] + 1.0) * np.exp(-beta_d * d)
    z = np.bincount(P["pa"], weights=attr, minlength=P["N"])
    return attr / np.maximum(z[P["pa"]], 1e-12)


def scenario_w(P, name, seed=1):
    K, t = P["K"], P["t0"]
    if name == "a_rush":
        w = 1 + 1.0 * np.exp(-((t - 495) / 45.0) ** 2) + 1.0 * np.exp(-((t - 1095) / 45.0) ** 2)
    elif name == "b_lognormal":
        w = np.exp(0.3 * np.random.default_rng(seed).standard_normal(K))
    elif name == "c_null":
        w = np.ones(K)
    elif name == "d_alternate":
        w = np.ones(K)
        for d in (0, 1):
            idx = np.where(P["dir"] == d)[0]
            idx = idx[np.argsort(P["t0"][idx], kind="stable")]
            w[idx[0::2]], w[idx[1::2]] = 0.7, 1.3
    else:
        raise ValueError(name)
    return w / w.mean()


def forward(P, s, pi):
    x = s[P["pa"]] * pi
    return np.bincount(P["cell"], weights=s, minlength=NC), P["Ma"] @ x


def make_truth(P, name, seed=1, noise=0.0, noise_seed=7):
    w = scenario_w(P, name, seed)
    pi = pi_true(P)
    ok_c = (P["elig_b"] > 0) & (P["B"] > 0)
    den = np.bincount(P["cell"], weights=w[P["tk"]] * P["nd"], minlength=NC)
    beta = np.where(ok_c & (den > 0), P["B"] / np.maximum(den, 1e-12), 0.0)
    s = w[P["tk"]] * beta[P["cell"]] * P["nd"]
    B, A = forward(P, s, pi)
    if noise:
        rng = np.random.default_rng(noise_seed)
        B = B * np.clip(1 + noise * rng.standard_normal(NC), .5, None)
        A = A * np.clip(1 + noise * rng.standard_normal(NC), .5, None)
    return dict(w=w, beta=beta, pi=pi, B=B, A=A)


def fit(P, B, A, mode, pi_known=None, off=10.0, lam=0.01, maxiter=3000):
    """mode 'E1': pi fixed (true). 'E2': pi free via softmax logits, KL(pi||uniform) weight lam on boarding mass."""
    K, N, V = P["K"], P["N"], P["V"]
    cellE = P["cell"]
    eb, ea = P["elig_b"] > 0, P["elig_a"] > 0
    wb, wa = eb / (B + off), ea / (A + off)
    mask = P["nd"] & (B[cellE] > 0)
    n_e = np.maximum(P["n_e"], 1)
    beta0 = np.where(np.bincount(cellE, weights=mask.astype(float), minlength=NC) > 0,
                     B / np.maximum(np.bincount(cellE, weights=mask.astype(float), minlength=NC), 1), 1e-3)
    th0 = np.concatenate([np.zeros(K), np.log(np.maximum(beta0, 1e-3)), np.zeros(V) if mode == "E2" else (np.zeros(NC + 1) if mode == "E3" else [])])
    dist = (pb - pa).astype(float) if False else None
    pa, pb = P["pa"], P["pb"]
    dist = (pb - pa).astype(float)

    def unpack(th):
        lw, lb = th[:K], th[K:K + NC]
        s = np.exp(lw)[P["tk"]] * np.exp(lb)[cellE] * mask
        if mode == "E2":
            e = np.exp(np.clip(th[K + NC:], -30, 30))
            z = np.bincount(pa, weights=e, minlength=N)
            pi = e / np.maximum(z[pa], 1e-300)
        elif mode == "E3":      # shared kernel: attraction alpha[cell(b)] and distance decay delta (free, flat init)
            lg = th[K + NC:K + 2 * NC][cellE[pb]] - th[-1] * dist
            e = np.exp(np.clip(lg, -30, 30))
            z = np.bincount(pa, weights=e, minlength=N)
            pi = e / np.maximum(z[pa], 1e-300)
        else:
            pi = pi_known
        return s, pi

    def fun(th):
        s, pi = unpack(th)
        Bm, Am = forward(P, s, pi)
        rB, rA = Bm - B, Am - A
        val = (wb * rB ** 2).sum() + (wa * rA ** 2).sum()
        gB, gAc = 2 * wb * rB, 2 * wa * rA
        gAv = gAc[cellE[pb]]
        ds = gB[cellE] + np.bincount(pa, weights=pi * gAv, minlength=N)
        if mode == "E2":
            lg = np.log(np.maximum(pi * n_e[pa], 1e-300))
            kl = np.bincount(pa, weights=pi * lg, minlength=N)
            val += lam * (s * kl).sum()
            ds = ds + lam * kl
            dpi = s[pa] * gAv + lam * s[pa] * (lg + 1)
            deta = pi * (dpi - np.bincount(pa, weights=pi * dpi, minlength=N)[pa])
        elif mode == "E3":
            dpi = s[pa] * gAv
            deta = pi * (dpi - np.bincount(pa, weights=pi * dpi, minlength=N)[pa])
        else:
            deta = None
        t = ds * s
        g = np.concatenate([np.bincount(P["tk"], weights=t, minlength=K), np.bincount(cellE, weights=t, minlength=NC)]
                           + ([deta] if mode == "E2" else [])
                           + ([np.bincount(cellE[pb], weights=deta, minlength=NC), [-(deta * dist).sum()]] if mode == "E3" else []))
        return val, g

    res = minimize(fun, th0, jac=True, method="L-BFGS-B", options=dict(maxiter=maxiter, maxfun=maxiter * 2, ftol=1e-14, gtol=1e-9, maxcor=20))
    s, pi = unpack(res.x)
    Bm, Am = forward(P, s, pi)
    w = np.exp(res.x[:K]); w = w / w.mean()
    relB = float(np.abs(Bm - B)[eb].sum() / max(B[eb].sum(), 1)); relA = float(np.abs(Am - A)[ea].sum() / max(A[ea].sum(), 1))
    return w, dict(nit=int(res.nit), converged=bool(res.success), objective=float(res.fun), rel_l1_B=relB, rel_l1_A=relA)


def within_hour_corr(P, wh, wt, by_dir=False):
    key = P["h0"] * 2 + P["dir"] if by_dir else P["h0"]
    a, b = wh.astype(float).copy(), wt.astype(float).copy()
    for g in np.unique(key):
        m = key == g
        a[m] -= a[m].mean(); b[m] -= b[m].mean()
    if a.std() < 1e-12 or b.std() < 1e-12:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def jacobians(P, truth, sd_frac=0.02):
    """Weighted Jacobians d(B,A)/dw. fixed: beta,pi at truth. profiled: beta(w)=B/sum_cell w (A rows only)."""
    import scipy.sparse as sp
    K = P["K"]; cell = P["cell"]; pa, pb, pk = P["pa"], P["pb"], P["pk"]
    beta, pi = truth["beta"], truth["pi"]
    eb, ea = P["elig_b"] > 0, P["elig_a"] > 0
    nd_ok = P["nd"] & (truth["B"][cell] > 0)
    JB = sp.csr_matrix((beta[cell[nd_ok]], (cell[nd_ok], P["tk"][nd_ok])), shape=(NC, K))
    JA = sp.csr_matrix((beta[cell[pa]] * pi * nd_ok[pa], (cell[pb], pk)), shape=(NC, K))
    sdB = sd_frac * truth["B"] + 1.0; sdA = sd_frac * truth["A"] + 1.0
    Jf = np.vstack([(sp.diags(1 / sdB) @ JB).toarray()[eb], (sp.diags(1 / sdA) @ JA).toarray()[ea]])
    # profiled: A(w) with beta_c = B_c / sum_{e in c} w
    def Afun(w):
        den = np.bincount(cell, weights=w[P["tk"]] * nd_ok, minlength=NC)
        b = np.where(den > 0, truth["B"] / np.maximum(den, 1e-12), 0.0)
        s = w[P["tk"]] * b[cell] * nd_ok
        return P["Ma"] @ (s[pa] * pi)
    w0 = truth["w"]; A0 = Afun(w0); h = 1e-4
    Jp = np.empty((int(ea.sum()), K))
    for k in range(K):
        w1 = w0.copy(); w1[k] += h
        Jp[:, k] = ((Afun(w1) - A0) / h / sdA)[ea]
    return Jf, Jp
