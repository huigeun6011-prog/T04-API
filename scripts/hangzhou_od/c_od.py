"""C선용 열차 단위 OD 역산. 대전 scripts/data_prep/gt_train_od.py의 변수·목적함수를 그대로 복제하고(원본 수정 없음) 대전 상수만 인자로 뺐다.
min_x  sum_cells (fit-obs)^2/(obs+10) + lam * sum_v (x log(x/q) - x + q),  x>=0, L-BFGS-B."""
import numpy as np
import scipy.sparse as sp
from scipy.optimize import minimize


def build_problem(tt, NH):
    ev, slices, NS = tt.ev, tt.slices, tt.NS
    N = len(ev); NC = NS * NH
    cell = (ev.station_idx * NH + ev.hour_idx).to_numpy()
    pk, pa, pb = [], [], []
    for k, (s, e) in enumerate(slices):
        n = e - s
        a_idx, b_idx = np.triu_indices(n, 1)
        pk.append(np.full(len(a_idx), k)); pa.append(s + a_idx); pb.append(s + b_idx)
    pk, pa, pb = (np.concatenate(v) for v in (pk, pa, pb))
    V = len(pa)
    Mb = sp.csr_matrix((np.ones(V), (cell[pa], np.arange(V))), shape=(NC, V))
    Ma = sp.csr_matrix((np.ones(V), (cell[pb], np.arange(V))), shape=(NC, V))
    elig_b = np.bincount(cell[(ev.is_destination == 0).to_numpy()], minlength=NC)
    elig_a = np.bincount(cell[(ev.is_origin == 0).to_numpy()], minlength=NC)
    hop = (ev.pos.to_numpy()[pb] - ev.pos.to_numpy()[pa]).astype(int)
    return dict(ev=ev, slices=slices, pk=pk, pa=pa, pb=pb, V=V, N=N, NC=NC, cell=cell, Mb=Mb, Ma=Ma, elig_b=elig_b, elig_a=elig_a, hop=hop)


def hop_g(P, kind, beta=None, truth_x=None, tilt=0.0):
    """pair별 거리 가중 g. uniform / gravity(exp(-beta*d)) / real(정답 OD의 거리별 비율, 오라클) 에 tilt: g*exp(tilt*d)."""
    d = P["hop"].astype(float)
    if kind == "uniform":
        g = np.ones(P["V"])
    elif kind == "gravity":
        g = np.exp(-beta * d)
    elif kind == "real":
        hops = P["hop"]
        cnt = np.bincount(hops, weights=truth_x, minlength=hops.max() + 1)
        board = np.bincount(P["pa"], weights=truth_x, minlength=P["N"])
        has = board[P["pa"]] > 0
        navail = np.bincount(hops[has], minlength=hops.max() + 1).astype(float)
        gd = np.maximum(cnt, 0.5) / np.maximum(navail, 1)
        g = gd[hops]
    else:
        raise ValueError(kind)
    return g * np.exp(tilt * d)


def base_q(P, B, g):
    """보딩 셀 질량 B(s,h)를 셀 안 이벤트에 균등 분배하고(대전 'uniform' 열차 가중), 이후 정차역에 g로 나눈다."""
    ev, cell = P["ev"], P["cell"]
    w = np.ones(P["N"]) * (ev.is_destination == 0).to_numpy()
    tot = np.bincount(cell, weights=w, minlength=P["NC"])
    m = np.where(tot[cell] > 0, B[cell] * w / np.maximum(tot[cell], 1e-12), 0.0)
    gs = np.bincount(P["pa"], weights=g, minlength=P["N"])
    return m[P["pa"]] * g / np.maximum(gs[P["pa"]], 1e-12)


def fit(P, B, A, q, lam, maxiter=20000):
    mask = q > 0
    qv = q[mask]
    Mb, Ma = P["Mb"][:, mask], P["Ma"][:, mask]
    wb = (P["elig_b"] > 0) / (B + 10.0)
    wa = (P["elig_a"] > 0) / (A + 10.0)

    def fun(v):
        rb, ra = Mb @ v - B, Ma @ v - A
        val = (wb * rb ** 2).sum() + (wa * ra ** 2).sum() + lam * (v * np.log(v / qv) - v + qv).sum()
        g = 2 * (Mb.T @ (wb * rb)) + 2 * (Ma.T @ (wa * ra)) + lam * np.log(v / qv)
        return val, g
    res = minimize(fun, qv.copy(), jac=True, method="L-BFGS-B", bounds=[(1e-12, None)] * len(qv),
                   options=dict(maxiter=maxiter, maxfun=maxiter * 2, ftol=1e-13, gtol=1e-8, maxcor=30))
    x = np.zeros(P["V"]); x[mask] = res.x
    pg = np.abs(res.jac[(res.x > 1e-10) | (res.jac < 0)]).max() if len(res.jac) else 0.0
    return x, dict(nit=int(res.nit), converged=bool(res.success), message=str(res.message), objective=float(res.fun), proj_grad_inf=float(pg))


def to_frame(P, x):
    ev = P["ev"].copy()
    N = P["N"]
    ev["board"] = np.bincount(P["pa"], weights=x, minlength=N)
    ev["alight"] = np.bincount(P["pb"], weights=x, minlength=N)
    ev["raw_load"] = np.concatenate([np.cumsum(ev.board.to_numpy()[s:e] - ev.alight.to_numpy()[s:e]) for s, e in P["slices"]])
    ev["load"] = np.maximum(ev.raw_load, 0)
    return ev


def marginal_stats(P, frame, B, A):
    fb = np.bincount(P["cell"], weights=frame.board.to_numpy(), minlength=P["NC"])
    fa = np.bincount(P["cell"], weights=frame.alight.to_numpy(), minlength=P["NC"])
    out = {}
    for name, fit_, obs, elig in (("B", fb, B, P["elig_b"]), ("A", fa, A, P["elig_a"])):
        e = elig > 0
        out[f"{name}_rel_l1_eligible"] = float(np.abs(fit_[e] - obs[e]).sum() / max(obs[e].sum(), 1))
        out[f"{name}_slack_nocell"] = float(obs[~e].sum())
        out[f"{name}_total_obs"] = float(obs.sum())
    return out
