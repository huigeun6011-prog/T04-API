import json
import numpy as np
from datetime import datetime, timedelta
from scipy.optimize import minimize
from collections import defaultdict
from pathlib import Path

STATION_NAMES = [
    "판암","신흥","대동","대전","중앙로","중구청","서대전네거리","오룡",
    "용문","탄방","시청","정부청사","갈마","월평","갑천","유성온천",
    "구암","현충원","월드컵경기장","노은","지족","반석"
]
STATION_TO_IDX = {name: i for i, name in enumerate(STATION_NAMES)}
N_STATIONS = len(STATION_NAMES)

def normalize_hour(h):
    if h == 24 or 0 <= h <= 4:
        return 24
    return h

def get_day_type(date_str):
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return "휴일" if dt.weekday() >= 5 else "평일"

def test_single_day(target_date="2025-11-04"):
    # 1. 로드
    next_date = (datetime.strptime(target_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    
    with open(f"./data/processed/subway/{target_date}.json", encoding="utf-8") as f:
        curr_subway = json.load(f)
    with open(f"./data/processed/subway/{next_date}.json", encoding="utf-8") as f:
        next_subway = json.load(f)
    
    time_path = "./data/processed/subway_time/subway_time_20250930.json"
    with open(time_path, encoding="utf-8") as f:
        subway_time = json.load(f)
        
    day_type = get_day_type(target_date)
    trains = [t for t in subway_time["trains"] if t["day_type"] == day_type]
    
    # 2. 역/시간대별 원본 승하차 집계 (5~24)
    # B[s, h], A[s, h]
    # h = 5..24 (20개 시간대)
    hours = list(range(5, 25))
    hour_to_idx = {h: i for i, h in enumerate(hours)}
    
    B_obs = np.zeros((N_STATIONS, len(hours)))
    A_obs = np.zeros((N_STATIONS, len(hours)))
    
    for sid_str, sdata in curr_subway["stations"].items():
        sid = int(sid_str)
        if not (101 <= sid <= 122): continue
        s_idx = sid - 101
        for h_str, cnt in sdata.get("boardings", {}).items():
            h = int(h_str)
            if 5 <= h <= 23:
                B_obs[s_idx, hour_to_idx[h]] += cnt
        for h_str, cnt in sdata.get("alightings", {}).items():
            h = int(h_str)
            if 5 <= h <= 23:
                A_obs[s_idx, hour_to_idx[h]] += cnt
                
    # 익일 0시 -> 24시 버킷
    for sid_str, sdata in next_subway["stations"].items():
        sid = int(sid_str)
        if not (101 <= sid <= 122): continue
        s_idx = sid - 101
        cnt_b = sdata.get("boardings", {}).get("0", 0)
        cnt_a = sdata.get("alightings", {}).get("0", 0)
        B_obs[s_idx, hour_to_idx[24]] += cnt_b
        A_obs[s_idx, hour_to_idx[24]] += cnt_a

    # 3. 열차별 정차 정보 파싱
    # train_stops: list of trains, each has stops: [(s_idx, h_idx, is_origin, is_dest)]
    parsed_trains = []
    # train counts per station & hour for up (dir=0) and down (dir=1)
    # n_trains_up[s, h], n_trains_down[s, h]
    n_up_board = np.zeros((N_STATIONS, len(hours)))
    n_up_alight = np.zeros((N_STATIONS, len(hours)))
    n_down_board = np.zeros((N_STATIONS, len(hours)))
    n_down_alight = np.zeros((N_STATIONS, len(hours)))
    
    for t in trains:
        dir_code = 0 if t["direction"] == "상행" else 1
        stops = t["stops"]
        n_stops = len(stops)
        t_stops = []
        for idx, st in enumerate(stops):
            s_idx = STATION_TO_IDX[st["station"]]
            hh = int(st["time"].split(":")[0])
            norm_h = normalize_hour(hh)
            h_idx = hour_to_idx[norm_h]
            is_orig = (idx == 0)
            is_dest = (idx == n_stops - 1)
            t_stops.append((s_idx, h_idx, is_orig, is_dest))
            
            if dir_code == 0: # 상행
                if not is_dest: n_up_board[s_idx, h_idx] += 1
                if not is_orig: n_up_alight[s_idx, h_idx] += 1
            else: # 하행
                if not is_dest: n_down_board[s_idx, h_idx] += 1
                if not is_orig: n_down_alight[s_idx, h_idx] += 1
                
        parsed_trains.append({
            "id": t["train_id"],
            "dir": dir_code,
            "stops": t_stops
        })
        
    print(f"Loaded {len(parsed_trains)} trains.")
    
    # 지리적 사전 확률 (Prior):
    # 판암(0) -> 반석(21).
    # 판암(0)에서는 상행(판암행) 승차 불가(0), 하행(반석행) 승차 100%.
    # 반석(21)에서는 하행(반석행) 승차 불가(0), 상행(판암행) 승차 100%.
    # 중간 역들은 s_idx / 21 에 비례하여 상행 승차 비율이 증가하는 경향.
    # p_init[s] = s_idx / 21
    # q_init[s] = 1.0 - (s_idx / 21)
    p_init = np.zeros((N_STATIONS, len(hours)))
    q_init = np.zeros((N_STATIONS, len(hours)))
    for s in range(N_STATIONS):
        # 상행 승차 비율: 반석(21)쪽일수록 판암으로 가는 상행을 많이 탐
        p_init[s, :] = s / (N_STATIONS - 1)
        # 상행 하차 비율: 판암(0)쪽일수록 반석에서 출발한 상행에서 많이 내림
        q_init[s, :] = 1.0 - (s / (N_STATIONS - 1))
        
    # 기점/종점 고정
    p_init[0, :] = 0.0   # 판암 상행 승차 0
    p_init[21, :] = 1.0  # 반석 상행 승차 1
    q_init[0, :] = 1.0   # 판암 상행 하차 1
    q_init[21, :] = 0.0  # 반석 상행 하차 0
    
    # 목적함수 계산 함수
    # x: flattened [p_mid, q_mid] for mid stations 1..20
    # mid stations = 20 stations * 20 hours = 400
    n_mid = (N_STATIONS - 2) * len(hours)
    
    def unpack(x):
        p = np.copy(p_init)
        q = np.copy(q_init)
        p_mid = x[:n_mid].reshape((N_STATIONS - 2, len(hours)))
        q_mid = x[n_mid:].reshape((N_STATIONS - 2, len(hours)))
        p[1:-1, :] = p_mid
        q[1:-1, :] = q_mid
        return p, q

    def simulate(p, q):
        # B_up, B_down, A_up, A_down
        B_up = p * B_obs
        B_down = (1.0 - p) * B_obs
        A_up = q * A_obs
        A_down = (1.0 - q) * A_obs
        
        # per-train share
        b_up_share = np.zeros_like(B_up)
        mask = n_up_board > 0
        b_up_share[mask] = B_up[mask] / n_up_board[mask]
        
        b_down_share = np.zeros_like(B_down)
        mask = n_down_board > 0
        b_down_share[mask] = B_down[mask] / n_down_board[mask]
        
        a_up_share = np.zeros_like(A_up)
        mask = n_up_alight > 0
        a_up_share[mask] = A_up[mask] / n_up_alight[mask]
        
        a_down_share = np.zeros_like(A_down)
        mask = n_down_alight > 0
        a_down_share[mask] = A_down[mask] / n_down_alight[mask]
        
        final_loads = []
        neg_loads = 0.0
        
        for t in parsed_trains:
            load = 0.0
            dir_code = t["dir"]
            for s_idx, h_idx, is_orig, is_dest in t["stops"]:
                if dir_code == 0:
                    b = 0.0 if is_dest else b_up_share[s_idx, h_idx]
                    a = 0.0 if is_orig else a_up_share[s_idx, h_idx]
                else:
                    b = 0.0 if is_dest else b_down_share[s_idx, h_idx]
                    a = 0.0 if is_orig else a_down_share[s_idx, h_idx]
                load += (b - a)
                if load < 0:
                    neg_loads += (-load) ** 2
            final_loads.append(load)
            
        return np.array(final_loads), neg_loads

    def loss_func(x):
        p, q = unpack(x)
        final_loads, neg_loads = simulate(p, q)
        term_loss = np.mean(final_loads ** 2)
        # prior regularization
        p_mid_init = p_init[1:-1, :].flatten()
        q_mid_init = q_init[1:-1, :].flatten()
        reg_loss = np.mean((x[:n_mid] - p_mid_init)**2) + np.mean((x[n_mid:] - q_mid_init)**2)
        return term_loss + 0.1 * neg_loads / len(parsed_trains) + 5.0 * reg_loss

    # 초기값 성능 평가
    x0 = np.concatenate([p_init[1:-1, :].flatten(), q_init[1:-1, :].flatten()])
    init_finals, _ = simulate(p_init, q_init)
    up_idx = [i for i, t in enumerate(parsed_trains) if t["dir"] == 0]
    down_idx = [i for i, t in enumerate(parsed_trains) if t["dir"] == 1]
    
    print("\n[초기 지리적 Prior 적용 시]")
    print(f"  전체 절대평균: {np.mean(np.abs(init_finals)):.2f}")
    print(f"  상행 평균: {np.mean(init_finals[up_idx]):.2f}, 절대평균: {np.mean(np.abs(init_finals[up_idx])):.2f}")
    print(f"  하행 평균: {np.mean(init_finals[down_idx]):.2f}, 절대평균: {np.mean(np.abs(init_finals[down_idx])):.2f}")

    print("\n최적화(L-BFGS-B) 실행 중...")
    bounds = [(0.0, 1.0)] * len(x0)
    res = minimize(loss_func, x0, method="L-BFGS-B", bounds=bounds, options={"maxiter": 100, "disp": True})
    
    opt_p, opt_q = unpack(res.x)
    opt_finals, _ = simulate(opt_p, opt_q)
    
    print("\n[최적화 후 결과]")
    print(f"  전체 절대평균: {np.mean(np.abs(opt_finals)):.2f}")
    print(f"  상행 평균: {np.mean(opt_finals[up_idx]):.2f}, 절대평균: {np.mean(np.abs(opt_finals[up_idx])):.2f}")
    print(f"  하행 평균: {np.mean(opt_finals[down_idx]):.2f}, 절대평균: {np.mean(np.abs(opt_finals[down_idx])):.2f}")

if __name__ == "__main__":
    test_single_day("2025-11-04")
