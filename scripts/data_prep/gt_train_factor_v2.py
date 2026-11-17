"""Phase D: exact/convex recovery tests of a per-train crowding factor w_k (SYNTHETIC ONLY).
With beta (cell boarding intensity) and pi (destination kernel) fixed, marginals are LINEAR in w:
  B(c) = beta_c * sum_k n_kc w_k ,  A(c') = sum_k w_k * sum_{b in c', a<b} beta[cell a] pi[a->b].
w is solved by bounded least squares on the normal equations (Cholesky + lsq_linear): exact, no maxiter.
beta is re-estimated per day in closed form from B (block coordinate descent); pi is oracle / shared kernel / wrong.
Real peak cases are never read here."""
import os
for v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[v] = "1"
import numpy as np
import scipy.sparse as sp
from scipy.interpolate import BSpline
from scipy.linalg import cholesky, solve_triangular
from scipy.optimize import lsq_linear, minimize
import gt_train_factor as tf

NC = tf.NC


def misspec_pi(P):
    d = (P["pb"] - P["pa"]).astype(float)
    A_cell = P["A"].reshape(22, 20).sum(1) + 1.0                    # station-level attraction (hour ignored)
    attr = A_cell[P["ev"].station_idx.to_numpy()[P["pb"]]] * (1 + d) ** -1.5
    z = np.bincount(P["pa"], weights=attr, minlength=P["N"])
    return attr / np.maximum(z[P["pa"]], 1e-12)


def make_days(P, scen, K, noise, truth_mode="main", pi_perturb=0.0, seed=1):
    w = tf.scenario_w(P, scen, seed)
    pit = tf.pi_true(P) if truth_mode == "main" else misspec_pi(P)
    ok_c = (P["elig_b"] > 0) & (P["B"] > 0)
    den = np.bincount(P["cell"], weights=w[P["tk"]] * P["nd"], minlength=NC)
    beta0 = np.where(ok_c & (den > 0), P["B"] / np.maximum(den, 1e-12), 0.0)
    rng = np.random.default_rng(1000 + seed)
    days = []
    for d in range(K):
        beta = beta0 * (np.exp(0.1 * rng.standard_normal()) if K > 1 else 1.0)
        pi = pit
        if pi_perturb:
            pi = pit * np.exp(pi_perturb * rng.standard_normal(len(pit)))
            pi = pi / np.maximum(np.bincount(P["pa"], weights=pi, minlength=P["N"])[P["pa"]], 1e-12)
        s = w[P["tk"]] * beta[P["cell"]] * P["nd"]
        B, A = tf.forward(P, s, pi)
        if noise:
            B = B * np.clip(1 + noise * rng.standard_normal(NC), .5, None)
            A = A * np.clip(1 + noise * rng.standard_normal(NC), .5, None)
        days.append(dict(B=B, A=A, beta_true=beta))
    return w, days


def jac_sparse(P, beta, pi, mask_cell):
    nd_ok = P["nd"] & mask_cell[P["cell"]]
    JB = sp.csr_matrix((beta[P["cell"]][nd_ok], (P["cell"][nd_ok], P["tk"][nd_ok])), shape=(NC, P["K"]))
    JA = sp.csr_matrix((beta[P["cell"][P["pa"]]] * pi * nd_ok[P["pa"]], (P["cell"][P["pb"]], P["pk"])), shape=(NC, P["K"]))
    return JB, JA


def normal_eq(P, days, betas, pi, off):
    K = P["K"]; H = np.zeros((K, K)); g = np.zeros(K)
    eb, ea = P["elig_b"] > 0, P["elig_a"] > 0
    for dd, beta in zip(days, betas):
        JB, JA = jac_sparse(P, beta, pi, dd["B"] > 0)
        wb, wa = eb / (dd["B"] + off), ea / (dd["A"] + off)
        H += (JB.T @ sp.diags(wb) @ JB).toarray() + (JA.T @ sp.diags(wa) @ JA).toarray()
        g += JB.T @ (wb * dd["B"]) + JA.T @ (wa * dd["A"])
    return H, g


def d2_operator(P, n):
    """second-difference rows over time-sorted trains, per direction."""
    rows = []
    for d in (0, 1):
        idx = np.where(P["dir"] == d)[0]; idx = idx[np.argsort(P["t0"][idx], kind="stable")]
        for i in range(len(idx) - 2):
            r = np.zeros(n); r[idx[i]], r[idx[i + 1]], r[idx[i + 2]] = 1, -2, 1; rows.append(r)
    return np.array(rows)


def bspline_basis(P, m):
    t = P["t0"]; lo, hi = t.min(), t.max()
    deg = 3
    inner = np.linspace(lo, hi, m - deg + 1)
    knots = np.concatenate([[lo] * deg, inner, [hi] * deg])
    Phi = np.column_stack([BSpline(knots, np.eye(m)[j], deg, extrapolate=False)(np.clip(t, lo, hi - 1e-9)) for j in range(m)])
    return np.nan_to_num(Phi)


def solve_w(H, g, eps, mode, pen_op=None, gamma=0.0, Phi=None, rho=0.0, lb=0.02):
    K = H.shape[0]; s0 = np.mean(np.diag(H)) + 1e-12
    if Phi is None:
        Hf = H + eps * s0 * np.eye(K); gf = g + eps * s0 * np.ones(K)
        if gamma:
            Hf = Hf + gamma * s0 * pen_op.T @ pen_op
        U = cholesky(Hf + 1e-10 * s0 * np.eye(K), lower=False)
        b = solve_triangular(U.T, gf, lower=True)
        res = lsq_linear(U, b, bounds=(lb, np.inf), method="bvls", lsq_solver="exact", tol=1e-12)
        return res.x
    m = Phi.shape[1]
    Hc = Phi.T @ H @ Phi; gc = Phi.T @ g; s0 = np.mean(np.diag(Hc)) + 1e-12
    D = np.diff(np.eye(m), 2, axis=0) if m > 2 else np.zeros((0, m))
    Hc = Hc + rho * s0 * D.T @ D + eps * s0 * np.eye(m); gc = gc + eps * s0 * np.ones(m)
    c = np.linalg.solve(Hc + 1e-10 * s0 * np.eye(m), gc)
    return np.maximum(Phi @ c, 0.05)


def profiled_day(P, w, dd, pi, off):
    """Residual and Jacobian (eligible A rows) with beta_c = B_c / sum_k n_kc w_k profiled out (exact derivative)."""
    cell, pa, pb, pk, tk = P["cell"], P["pa"], P["pb"], P["pk"], P["tk"]
    ea = P["elig_a"] > 0
    okc = dd["B"] > 0
    nd_ok = P["nd"] & okc[cell]
    D = np.bincount(cell, weights=w[tk] * nd_ok, minlength=NC)
    beta = np.where((D > 0) & okc, dd["B"] / np.maximum(D, 1e-12), 0.0)
    s = w[tk] * beta[cell] * nd_ok
    Am = P["Ma"] @ (s[pa] * pi)
    Jd = sp.csr_matrix((beta[cell[pa]] * pi * nd_ok[pa], (cell[pb], pk)), shape=(NC, P["K"]))
    gam = w[pk] * pi * nd_ok[pa] * np.where(D[cell[pa]] > 0, dd["B"][cell[pa]] / np.maximum(D[cell[pa]], 1e-12) ** 2, 0.0)
    M = sp.csr_matrix((gam, (cell[pb], cell[pa])), shape=(NC, NC))
    Nm = sp.csr_matrix((np.ones(nd_ok.sum()), (cell[nd_ok], tk[nd_ok])), shape=(NC, P["K"]))
    J = Jd - M @ Nm
    wa = ea / (dd["A"] + off)
    return (Am - dd["A"]), wa, J


def estimate(P, days, off=10.0, eps=1e-4, basis=0, gamma=0.0, rho=0.01, pi_mode="fixed", pi_fixed=None, beta_mode="est",
             outer=1, inner_pi=40, gn_iter=40):
    """beta_mode 'oracle': beta known (true) -> exact bounded linear LS on B and A rows.
    'est': beta profiled from B (exact), Levenberg-Marquardt Gauss-Newton on w (or basis coefficients) with exact Jacobian."""
    K = P["K"]; cell, pa, pb = P["cell"], P["pa"], P["pb"]; N = P["N"]
    dist = (pb - pa).astype(float); ea = P["elig_a"] > 0
    pen = d2_operator(P, K) if gamma else None
    Phi = bspline_basis(P, basis) if basis else np.eye(K)
    m = Phi.shape[1]
    Dm = np.diff(np.eye(m), 2, axis=0) if (basis and m > 2) else np.zeros((0, m))
    pi = pi_fixed if pi_fixed is not None else tf.pi_true(P)
    alpha = np.zeros(NC + 1)
    if pi_mode == "kernel":
        def kern(th):
            lg = th[:NC][cell[pb]] - th[NC] * dist
            e = np.exp(np.clip(lg, -30, 30)); z = np.bincount(pa, weights=e, minlength=N)
            return e / np.maximum(z[pa], 1e-300)
        pi = kern(alpha)
    info = dict(lm_iters=0)
    if beta_mode == "oracle":
        H, g = normal_eq(P, days, [dd["beta_true"] for dd in days], pi, off)
        w = solve_w(H, g, eps, "ls", pen, gamma, Phi if basis else None, rho)
        info.update(converged=True, lm_iters=0)
        return w / w.mean(), info
    theta = np.linalg.lstsq(Phi, np.ones(K), rcond=None)[0]
    wcur = lambda th: np.maximum(Phi @ th, 0.02)
    def objective(th, w_only=False):
        w = wcur(th); val = 0.0
        for dd in days:
            r, wa, _ = profiled_day(P, w, dd, pi, off) if False else (None, None, None)
        return val
    mu = 1e-3; hist = []
    for rnd in range(outer):
        # LM iterations on w for the current pi
        for it in range(gn_iter):
            w = wcur(theta)
            H = np.zeros((K, K)); g = np.zeros(K); f = 0.0
            for dd in days:
                r, wa, J = profiled_day(P, w, dd, pi, off)
                Jd = J.toarray()
                H += Jd.T @ (wa[:, None] * Jd); g += Jd.T @ (wa * r); f += float((wa * r ** 2).sum())
            Hc, gc = Phi.T @ H @ Phi, Phi.T @ g
            s0 = np.mean(np.diag(Hc)) + 1e-12
            reg_H = eps * s0 * np.eye(m); reg_g = eps * s0 * (theta - np.linalg.lstsq(Phi, np.ones(K), rcond=None)[0])
            if basis:
                reg_H = reg_H + rho * s0 * Dm.T @ Dm; reg_g = reg_g + rho * s0 * Dm.T @ (Dm @ theta)
            elif gamma:
                reg_H = reg_H + gamma * s0 * pen.T @ pen; reg_g = reg_g + gamma * s0 * pen.T @ (pen @ theta)
            def total(th):
                w2 = wcur(th); v = 0.0
                for dd in days:
                    r2, wa2, _ = profiled_day(P, w2, dd, pi, off)
                    v += float((wa2 * r2 ** 2).sum())
                t0_ = th - np.linalg.lstsq(Phi, np.ones(K), rcond=None)[0]
                v += eps * s0 * float(t0_ @ t0_)
                if basis: v += rho * s0 * float((Dm @ th) @ (Dm @ th))
                elif gamma: v += gamma * s0 * float((pen @ th) @ (pen @ th))
                return v
            base = total(theta)
            while True:
                step = np.linalg.solve(Hc + reg_H + mu * s0 * np.eye(m), -(gc + reg_g))
                if total(theta + step) < base or mu > 1e8:
                    break
                mu *= 4
            theta = theta + step if total(theta + step) < base else theta
            mu = max(mu / 3, 1e-9)
            hist.append(float(np.abs(wcur(theta) / wcur(theta).mean() - w / w.mean()).max()))
            info["lm_iters"] = it + 1
            if hist[-1] < 1e-7:
                break
        if pi_mode == "kernel":
            w = wcur(theta)
            def fun(th):
                p_ = kern(th); val = 0.0; ge = np.zeros(len(pa))
                for dd in days:
                    okc = dd["B"] > 0; nd_ok = P["nd"] & okc[cell]
                    D = np.bincount(cell, weights=w[P["tk"]] * nd_ok, minlength=NC)
                    beta = np.where((D > 0) & okc, dd["B"] / np.maximum(D, 1e-12), 0.0)
                    s = w[P["tk"]] * beta[cell] * nd_ok
                    Am = P["Ma"] @ (s[pa] * p_); wa = ea / (dd["A"] + off); r = Am - dd["A"]
                    val += (wa * r ** 2).sum()
                    dpi = s[pa] * (2 * wa * r)[cell[pb]]
                    ge += p_ * (dpi - np.bincount(pa, weights=p_ * dpi, minlength=N)[pa])
                return val, np.concatenate([np.bincount(cell[pb], weights=ge, minlength=NC), [-(ge * dist).sum()]])
            res = minimize(fun, alpha, jac=True, method="L-BFGS-B", options=dict(maxiter=inner_pi))
            alpha = res.x; pi = kern(alpha); info["kernel_obj"] = float(res.fun)
    w = wcur(theta)
    info["final_w_change"] = hist[-1] if hist else 0.0
    info["converged"] = bool(hist and hist[-1] < 1e-4)
    return w / w.mean(), info


def binned_metrics(P, wh, wt):
    out = {}
    t = P["t0"]
    for width in (60, 30, 15, 5):
        b = (t // width).astype(int)
        ub = np.unique(b)
        mh = np.array([wh[b == u].mean() for u in ub]); mt = np.array([wt[b == u].mean() for u in ub])
        ok = len(ub) >= 3 and mt.std() > 1e-9 and mh.std() > 1e-12
        out[f"bin{width}_corr"] = float(np.corrcoef(mh, mt)[0, 1]) if ok else np.nan
        out[f"bin{width}_relerr_median"] = float(np.median(np.abs(mh - mt) / mt))
    return out
