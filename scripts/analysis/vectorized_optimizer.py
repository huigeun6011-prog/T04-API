import json
import torch
import numpy as np
from datetime import datetime, timedelta

STATION_NAMES = [
    "판암","신흥","대동","대전","중앙로","중구청","서대전네거리","오룡",
    "용문","탄방","시청","정부청사","갈마","월평","갑천","유성온천",
    "구암","현충원","월드컵경기장","노은","지족","반석"
]
STATION_TO_IDX = {name: i for i, name in enumerate(STATION_NAMES)}
N_STATIONS = len(STATION_NAMES)
HOURS = list(range(5, 25))
N_HOURS = len(HOURS)
HOUR_TO_IDX = {h: i for i, h in enumerate(HOURS)}

def normalize_hour(h):
    if h == 24 or 0 <= h <= 4:
        return 24
    return h

def get_day_type(date_str):
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return "휴일" if dt.weekday() >= 5 else "평일"

def run_vectorized_test(target_date="2025-11-04"):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    next_date = (datetime.strptime(target_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    
    with open(f"./data/processed/subway/{target_date}.json", encoding="utf-8") as f:
        curr_subway = json.load(f)
    with open(f"./data/processed/subway/{next_date}.json", encoding="utf-8") as f:
        next_subway = json.load(f)
    with open("./data/processed/subway_time/subway_time_20250930.json", encoding="utf-8") as f:
        subway_time = json.load(f)
        
    day_type = get_day_type(target_date)
    trains = [t for t in subway_time["trains"] if t["day_type"] == day_type]
    
    B_obs = np.zeros((N_STATIONS, N_HOURS), dtype=np.float32)
    A_obs = np.zeros((N_STATIONS, N_HOURS), dtype=np.float32)
    
    for sid_str, sdata in curr_subway["stations"].items():
        sid = int(sid_str)
        if not (101 <= sid <= 122): continue
        s_idx = sid - 101
        for h_str, cnt in sdata.get("boardings", {}).items():
            h = int(h_str)
            if 5 <= h <= 23:
                B_obs[s_idx, HOUR_TO_IDX[h]] += cnt
        for h_str, cnt in sdata.get("alightings", {}).items():
            h = int(h_str)
            if 5 <= h <= 23:
                A_obs[s_idx, HOUR_TO_IDX[h]] += cnt
                
    for sid_str, sdata in next_subway["stations"].items():
        sid = int(sid_str)
        if not (101 <= sid <= 122): continue
        s_idx = sid - 101
        cnt_b = sdata.get("boardings", {}).get("0", 0)
        cnt_a = sdata.get("alightings", {}).get("0", 0)
        B_obs[s_idx, HOUR_TO_IDX[24]] += cnt_b
        A_obs[s_idx, HOUR_TO_IDX[24]] += cnt_a

    n_up_board = np.zeros((N_STATIONS, N_HOURS), dtype=np.float32)
    n_up_alight = np.zeros((N_STATIONS, N_HOURS), dtype=np.float32)
    n_down_board = np.zeros((N_STATIONS, N_HOURS), dtype=np.float32)
    n_down_alight = np.zeros((N_STATIONS, N_HOURS), dtype=np.float32)
    
    # 텐서 인덱스 빌드
    train_slices = [] # (start_idx, end_idx, dir_code)
    all_s_idx = []
    all_h_idx = []
    all_dir = []
    all_is_dest = []
    all_is_orig = []
    
    cur_idx = 0
    for t in trains:
        dir_code = 0 if t["direction"] == "상행" else 1
        stops = t["stops"]
        n_stops = len(stops)
        start_idx = cur_idx
        for idx, st in enumerate(stops):
            s_idx = STATION_TO_IDX[st["station"]]
            hh = int(st["time"].split(":")[0])
            norm_h = normalize_hour(hh)
            h_idx = HOUR_TO_IDX[norm_h]
            is_orig = (idx == 0)
            is_dest = (idx == n_stops - 1)
            
            all_s_idx.append(s_idx)
            all_h_idx.append(h_idx)
            all_dir.append(dir_code)
            all_is_dest.append(1.0 if is_dest else 0.0)
            all_is_orig.append(1.0 if is_orig else 0.0)
            cur_idx += 1
            
            if dir_code == 0:
                if not is_dest: n_up_board[s_idx, h_idx] += 1
                if not is_orig: n_up_alight[s_idx, h_idx] += 1
            else:
                if not is_dest: n_down_board[s_idx, h_idx] += 1
                if not is_orig: n_down_alight[s_idx, h_idx] += 1
                
        train_slices.append((start_idx, cur_idx, dir_code))

    # 텐서화
    B_t = torch.tensor(B_obs, device=device)
    A_t = torch.tensor(A_obs, device=device)
    n_up_b_t = torch.tensor(n_up_board, device=device).clamp(min=1e-5)
    n_up_a_t = torch.tensor(n_up_alight, device=device).clamp(min=1e-5)
    n_dn_b_t = torch.tensor(n_down_board, device=device).clamp(min=1e-5)
    n_dn_a_t = torch.tensor(n_down_alight, device=device).clamp(min=1e-5)

    idx_s = torch.tensor(all_s_idx, dtype=torch.long, device=device)
    idx_h = torch.tensor(all_h_idx, dtype=torch.long, device=device)
    t_dir = torch.tensor(all_dir, dtype=torch.float32, device=device) # 0=up, 1=dn
    m_dest = torch.tensor(all_is_dest, dtype=torch.float32, device=device)
    m_orig = torch.tensor(all_is_orig, dtype=torch.float32, device=device)

    # 파라미터 초기화
    p_prior = np.zeros((N_STATIONS, N_HOURS), dtype=np.float32)
    q_prior = np.zeros((N_STATIONS, N_HOURS), dtype=np.float32)
    for s in range(N_STATIONS):
        p_prior[s, :] = s / (N_STATIONS - 1)
        q_prior[s, :] = 1.0 - (s / (N_STATIONS - 1))
    p_prior = np.clip(p_prior, 0.01, 0.99)
    q_prior = np.clip(q_prior, 0.01, 0.99)
    
    p_logit_init = np.log(p_prior[1:-1, :] / (1.0 - p_prior[1:-1, :]))
    q_logit_init = np.log(q_prior[1:-1, :] / (1.0 - q_prior[1:-1, :]))
    
    p_logits = torch.nn.Parameter(torch.tensor(p_logit_init, device=device))
    q_logits = torch.nn.Parameter(torch.tensor(q_logit_init, device=device))
    
    prior_p_t = torch.tensor(p_prior[1:-1, :], device=device)
    prior_q_t = torch.tensor(q_prior[1:-1, :], device=device)
    
    optimizer = torch.optim.Adam([p_logits, q_logits], lr=0.1)

    def get_full_pq():
        p_mid = torch.sigmoid(p_logits)
        q_mid = torch.sigmoid(q_logits)
        p_0 = torch.zeros((1, N_HOURS), device=device)
        p_1 = torch.ones((1, N_HOURS), device=device)
        q_1 = torch.ones((1, N_HOURS), device=device)
        q_0 = torch.zeros((1, N_HOURS), device=device)
        p = torch.cat([p_0, p_mid, p_1], dim=0)
        q = torch.cat([q_1, q_mid, q_0], dim=0)
        return p, q

    import time
    t0 = time.time()
    
    print(f"최적화 시작 (Total stops: {len(all_s_idx)}, Trains: {len(train_slices)})")
    
    for epoch in range(300):
        optimizer.zero_grad()
        p, q = get_full_pq()
        
        # Grid shares
        b_up_grid = (p * B_t) / n_up_b_t
        b_dn_grid = ((1.0 - p) * B_t) / n_dn_b_t
        a_up_grid = (q * A_t) / n_up_a_t
        a_dn_grid = ((1.0 - q) * A_t) / n_dn_a_t
        
        # 1D vectorized indexing
        b_up_stops = b_up_grid[idx_s, idx_h] * (1.0 - m_dest)
        b_dn_stops = b_dn_grid[idx_s, idx_h] * (1.0 - m_dest)
        a_up_stops = a_up_grid[idx_s, idx_h] * (1.0 - m_orig)
        a_dn_stops = a_dn_grid[idx_s, idx_h] * (1.0 - m_orig)
        
        # blend based on direction (0=up, 1=dn)
        b_stops = (1.0 - t_dir) * b_up_stops + t_dir * b_dn_stops
        a_stops = (1.0 - t_dir) * a_up_stops + t_dir * a_dn_stops
        net_stops = b_stops - a_stops
        
        # 열차별 cumsum 및 종점 load
        term_loads = []
        neg_penalties = []
        for st, en, d in train_slices:
            train_net = net_stops[st:en]
            train_load = torch.cumsum(train_net, dim=0)
            term_loads.append(train_load[-1])
            neg_penalties.append(torch.relu(-train_load))
            
        term_tensor = torch.stack(term_loads)
        all_neg = torch.cat(neg_penalties)
        
        loss_term = torch.mean(term_tensor ** 2)
        loss_neg = torch.mean(all_neg ** 2)
        loss_prior = torch.mean((torch.sigmoid(p_logits) - prior_p_t)**2) + torch.mean((torch.sigmoid(q_logits) - prior_q_t)**2)
        
        loss = loss_term + 1.0 * loss_neg + 2.0 * loss_prior
        loss.backward()
        optimizer.step()
        
        if (epoch + 1) % 50 == 0 or epoch == 0:
            with torch.no_grad():
                up_mask = [d == 0 for _, _, d in train_slices]
                dn_mask = [d == 1 for _, _, d in train_slices]
                up_f = term_tensor[up_mask].cpu().numpy()
                dn_f = term_tensor[dn_mask].cpu().numpy()
                all_f = term_tensor.cpu().numpy()
                print(f"Epoch {epoch+1:3d} | Loss: {loss.item():.2f} | "
                      f"전체 절대평균: {np.mean(np.abs(all_f)):.2f}명 | "
                      f"상행: {np.mean(up_f):+.2f} (절대 {np.mean(np.abs(up_f)):.2f}) | "
                      f"하행: {np.mean(dn_f):+.2f} (절대 {np.mean(np.abs(dn_f)):.2f})")
                      
    print(f"\n최적화 완료! 소요 시간: {time.time() - t0:.2f}초")

if __name__ == "__main__":
    run_vectorized_test("2025-11-04")
