"""C선용 기존 Adam GT 방식(대전 gt_arrival_curve.solve_day의 baseline 분기) 복제. 원본 수정 없음. 기준: criteria.md '추가 기준'.
역·시간별 상행 승차 분배율 p, 상행 하차 분배율 q를 sigmoid 로짓으로 학습한다. 승차는 같은 셀의 가능한 열차에 균등, 하차도 열차당 균등.
손실 = mean(종점 재차^2) + mean(relu(-재차)^2) + 2*prior_loss, Adam lr=0.1, 최저 손실 iterate 복원."""
import numpy as np
import pandas as pd
import torch


def feasible_shares(up_share, up_count, down_count):
    up_ok, down_ok = up_count > 0, down_count > 0
    up_weight = torch.where(up_ok, torch.where(down_ok, up_share, 1.0), 0.0)
    down_weight = torch.where(down_ok, torch.where(up_ok, 1.0 - up_share, 1.0), 0.0)
    return up_weight, down_weight


def solve(tt, B, A, NH, epochs=1000, lr=0.1):
    torch.set_num_threads(1)
    NS, ev, K = tt.NS, tt.ev, tt.K
    T = lambda x, **k: torch.tensor(x, **k)
    sidx, hidx = ev.station_idx.to_numpy(), ev.hour_idx.to_numpy()
    d = ev.dir_code.to_numpy()                       # 0 = 상행(toward_34) 으로 대응
    dest, orig = ev.is_destination.to_numpy(), ev.is_origin.to_numpy()
    n_ub, n_ua, n_db, n_da = (np.zeros((NS, NH), np.float32) for _ in range(4))
    np.add.at(n_ub, (sidx[(d == 0) & (dest == 0)], hidx[(d == 0) & (dest == 0)]), 1)
    np.add.at(n_ua, (sidx[(d == 0) & (orig == 0)], hidx[(d == 0) & (orig == 0)]), 1)
    np.add.at(n_db, (sidx[(d == 1) & (dest == 0)], hidx[(d == 1) & (dest == 0)]), 1)
    np.add.at(n_da, (sidx[(d == 1) & (orig == 0)], hidx[(d == 1) & (orig == 0)]), 1)
    B_t, A_t = T(B.reshape(NS, NH).astype(np.float32)), T(A.reshape(NS, NH).astype(np.float32))
    nub, nua, ndb, nda = T(n_ub), T(n_ua), T(n_db), T(n_da)
    idx_s, idx_h = T(sidx, dtype=torch.long), T(hidx, dtype=torch.long)
    t_dir, m_dest, m_orig = T(d.astype(np.float32)), T(dest.astype(np.float32)), T(orig.astype(np.float32))

    pp = np.clip(np.array([[s / (NS - 1)] * NH for s in range(NS)], np.float32), .01, .99)
    qp = np.clip(1 - np.array([[s / (NS - 1)] * NH for s in range(NS)], np.float32), .01, .99)
    pl0 = np.log(pp[1:-1] / (1 - pp[1:-1])); ql0 = np.log(qp[1:-1] / (1 - qp[1:-1]))
    p_logits = torch.nn.Parameter(T(pl0)); q_logits = torch.nn.Parameter(T(ql0))
    prior_p, prior_q = T(pp[1:-1]), T(qp[1:-1])
    opt = torch.optim.Adam([p_logits, q_logits], lr=lr)
    p_ident = T(((nub > 0) & (ndb > 0))[1:-1].numpy())
    q_ident = T(((nua > 0) & (nda > 0))[1:-1].numpy())
    n = NS
    gidx = T(np.arange(K * n).reshape(K, n), dtype=torch.long)

    def full_pq():
        z, o = torch.zeros((1, NH)), torch.ones((1, NH))
        return torch.cat([z, torch.sigmoid(p_logits), o]), torch.cat([o, torch.sigmoid(q_logits), z])

    def stops(p, q):
        pu, pd_ = feasible_shares(p, nub, ndb); qu, qd = feasible_shares(q, nua, nda)
        a_up, a_dn = qu * A_t / nua.clamp(min=1), qd * A_t / nda.clamp(min=1)
        a = ((1 - t_dir) * a_up[idx_s, idx_h] + t_dir * a_dn[idx_s, idx_h]) * (1 - m_orig)
        b_up, b_dn = pu * B_t / nub.clamp(min=1), pd_ * B_t / ndb.clamp(min=1)
        b = ((1 - t_dir) * b_up[idx_s, idx_h] + t_dir * b_dn[idx_s, idx_h]) * (1 - m_dest)
        return b, a

    def prior_loss():
        d1 = (torch.sigmoid(p_logits) - prior_p) ** 2; d2 = (torch.sigmoid(q_logits) - prior_q) ** 2
        return d1.mul(p_ident).sum() / p_ident.sum().clamp(min=1) + d2.mul(q_ident).sum() / q_ident.sum().clamp(min=1)

    best, best_ep, best_par = float("inf"), 0, None
    for ep in range(epochs):
        opt.zero_grad()
        p, q = full_pq(); b, a = stops(p, q)
        load = torch.cumsum((b - a)[gidx], dim=1)
        term = load[:, -1]
        loss = torch.mean(term ** 2) + torch.mean(torch.relu(-load) ** 2) + 2.0 * prior_loss()
        v = float(loss.detach())
        if v < best:
            best, best_ep, best_par = v, ep + 1, (p_logits.detach().clone(), q_logits.detach().clone())
        loss.backward(); opt.step()
    with torch.no_grad():
        p_logits.copy_(best_par[0]); q_logits.copy_(best_par[1])
        p, q = full_pq(); b, a = stops(p, q)
    b, a = b.detach().numpy().astype(np.float64), a.detach().numpy().astype(np.float64)
    frame = ev.copy()
    frame["board"], frame["alight"] = b, a
    frame["raw_load"] = np.concatenate([np.cumsum(b[s:e] - a[s:e]) for s, e in tt.slices])
    frame["load"] = np.maximum(frame.raw_load, 0)
    return frame, dict(best_epoch=best_ep, best_loss=float(best), board_alloc_total=float(b.sum()), alight_alloc_total=float(a.sum()),
                       board_obs_total=float(B.sum()), alight_obs_total=float(A.sum()))
