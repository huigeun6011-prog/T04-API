"""
generate_ground_truth.py
과거 승하차 데이터와 시각표, 날씨 데이터를 결합하고,
물리 제약(종점 잔류 인원 최소화, 음수 재차 방지, 개찰구 총량 보존)을 유도하는
탄력적 벡터화 최적화(Soft-constrained Optimization)를 수행하여
열차별/역별 물리적 재차인원 정답 데이터셋(Ground Truth)을 생성합니다.
"""

import os
import sys
import json
import argparse
import time

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

import numpy as np
import pandas as pd
import torch

# ==========================================
# 1. 상수 정의
# ==========================================
SUBWAY_DIR = Path("./data/processed/subway")
WEATHER_DIR = Path("./data/raw/weather")
SUBWAY_TIME_BEFORE = Path("./data/processed/subway_time/subway_time_20250930.json")
SUBWAY_TIME_AFTER = Path("./data/processed/subway_time/subway_time_20260330.json")
OUTPUT_DIR = Path("./outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PLAN_CHANGE_DATE = "2026-03-30"

STATION_NAMES = [
    "판암","신흥","대동","대전","중앙로","중구청","서대전네거리","오룡",
    "용문","탄방","시청","정부청사","갈마","월평","갑천","유성온천",
    "구암","현충원","월드컵경기장","노은","지족","반석"
]
STATION_TO_IDX = {name: i for i, name in enumerate(STATION_NAMES)}
N_STATIONS = len(STATION_NAMES)

HOURS = list(range(5, 25))  # 5, 6, ..., 23, 24 (24 = 자정 넘김)
N_HOURS = len(HOURS)
HOUR_TO_IDX = {h: i for i, h in enumerate(HOURS)}

HOLIDAYS = {
    "2024-12-25",
    "2025-01-01", "2025-01-27", "2025-01-28", "2025-01-29", "2025-01-30",
    "2025-03-01", "2025-03-03", "2025-05-05", "2025-05-06",
    "2025-06-03", "2025-06-06", "2025-08-15",
    "2025-10-03", "2025-10-05", "2025-10-06", "2025-10-07", "2025-10-08", "2025-10-09",
    "2025-12-25",
    "2026-01-01", "2026-02-16", "2026-02-17", "2026-02-18",
    "2026-03-01", "2026-03-02", "2026-05-05", "2026-05-24", "2026-05-25",
    "2026-06-06", "2026-08-15", "2026-08-17",
    "2026-09-24", "2026-09-25", "2026-09-26",
    "2026-10-03", "2026-10-05", "2026-10-09", "2026-12-25",
}

# ==========================================
# 2. 유틸리티 함수
# ==========================================
def normalize_hour(h):
    if h == 24 or 0 <= h <= 4:
        return 24
    return h

def get_day_type(date_str):
    if date_str in HOLIDAYS:
        return "휴일"
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return "휴일" if dt.weekday() >= 5 else "평일"

_TIME_SCHEDULE_CACHE = {}

def get_subway_trains(date_str, day_type):
    """
    해당 날짜 및 요일구분에 맞는 열차 목록 반환.
    2026-03-30 이후 휴일의 경우 20250930 시각표의 휴일을 폴백으로 사용.
    """
    if "before" not in _TIME_SCHEDULE_CACHE:
        with open(SUBWAY_TIME_BEFORE, encoding="utf-8") as f:
            _TIME_SCHEDULE_CACHE["before"] = json.load(f)
    if "after" not in _TIME_SCHEDULE_CACHE:
        with open(SUBWAY_TIME_AFTER, encoding="utf-8") as f:
            _TIME_SCHEDULE_CACHE["after"] = json.load(f)

    if date_str >= PLAN_CHANGE_DATE and day_type == "평일":
        trains_all = _TIME_SCHEDULE_CACHE["after"]["trains"]
    else:
        trains_all = _TIME_SCHEDULE_CACHE["before"]["trains"]

    return [t for t in trains_all if t["day_type"] == day_type]

# ==========================================
# 3. 1일치 최적화 및 시뮬레이션
# ==========================================
def process_single_date(date_str, subway_file, next_subway_file, weather_file, device):
    with open(subway_file, encoding="utf-8") as f:
        curr_subway = json.load(f)
    
    next_subway = None
    if next_subway_file and os.path.exists(next_subway_file):
        with open(next_subway_file, encoding="utf-8") as f:
            next_subway = json.load(f)
            
    with open(weather_file, encoding="utf-8") as f:
        weather_raw = json.load(f)["hourly"]

    day_type = get_day_type(date_str)
    plan_version = 1 if date_str >= PLAN_CHANGE_DATE else 0
    trains = get_subway_trains(date_str, day_type)
    if not trains:
        return []

    # 1) 역·시간대별 관측 승하차 집계
    B_obs = np.zeros((N_STATIONS, N_HOURS), dtype=np.float32)
    A_obs = np.zeros((N_STATIONS, N_HOURS), dtype=np.float32)

    for sid_str, sdata in curr_subway.get("stations", {}).items():
        sid = int(sid_str)
        if not (101 <= sid <= 122):
            continue
        s_idx = sid - 101
        for h_str, cnt in sdata.get("boardings", {}).items():
            h = int(h_str)
            if 5 <= h <= 23:
                B_obs[s_idx, HOUR_TO_IDX[h]] += cnt
        for h_str, cnt in sdata.get("alightings", {}).items():
            h = int(h_str)
            if 5 <= h <= 23:
                A_obs[s_idx, HOUR_TO_IDX[h]] += cnt

    # 익일 0시 -> 당일 24시 버킷 귀속
    if next_subway is not None:
        for sid_str, sdata in next_subway.get("stations", {}).items():
            sid = int(sid_str)
            if not (101 <= sid <= 122):
                continue
            s_idx = sid - 101
            b0 = sdata.get("boardings", {}).get("0", 0)
            a0 = sdata.get("alightings", {}).get("0", 0)
            B_obs[s_idx, HOUR_TO_IDX[24]] += b0
            A_obs[s_idx, HOUR_TO_IDX[24]] += a0

    # 2) 열차 정차 인덱싱 빌드
    n_up_board = np.zeros((N_STATIONS, N_HOURS), dtype=np.float32)
    n_up_alight = np.zeros((N_STATIONS, N_HOURS), dtype=np.float32)
    n_down_board = np.zeros((N_STATIONS, N_HOURS), dtype=np.float32)
    n_down_alight = np.zeros((N_STATIONS, N_HOURS), dtype=np.float32)

    train_slices = []
    all_s_idx = []
    all_h_idx = []
    all_dir = []
    all_is_dest = []
    all_is_orig = []
    stop_meta = []

    cur_idx = 0
    for t in trains:
        train_id = t["train_id"]
        dir_code = 0 if t["direction"] == "상행" else 1
        stops = t["stops"]
        n_stops = len(stops)
        start_idx = cur_idx

        for idx, st in enumerate(stops):
            s_name = st["station"]
            if s_name not in STATION_TO_IDX:
                continue
            s_idx = STATION_TO_IDX[s_name]
            time_str = st["time"]
            hh = int(time_str.split(":")[0])
            norm_h = normalize_hour(hh)
            h_idx = HOUR_TO_IDX[norm_h]

            is_orig = (idx == 0)
            is_dest = (idx == n_stops - 1)

            all_s_idx.append(s_idx)
            all_h_idx.append(h_idx)
            all_dir.append(dir_code)
            all_is_dest.append(1.0 if is_dest else 0.0)
            all_is_orig.append(1.0 if is_orig else 0.0)

            stop_meta.append({
                "train_id": train_id,
                "direction": t["direction"],
                "dir_code": dir_code,
                "station": s_name,
                "station_idx": s_idx,
                "time": time_str,
                "hour": norm_h,
                "hour_idx": h_idx,
                "is_origin": 1 if is_orig else 0,
                "is_destination": 1 if is_dest else 0,
            })
            cur_idx += 1

            if dir_code == 0:
                if not is_dest: n_up_board[s_idx, h_idx] += 1
                if not is_orig: n_up_alight[s_idx, h_idx] += 1
            else:
                if not is_dest: n_down_board[s_idx, h_idx] += 1
                if not is_orig: n_down_alight[s_idx, h_idx] += 1

        train_slices.append((start_idx, cur_idx, dir_code))

    if not all_s_idx:
        return []

    # 3) PyTorch 텐서 변환
    B_t = torch.tensor(B_obs, device=device)
    A_t = torch.tensor(A_obs, device=device)
    n_up_b_t = torch.tensor(n_up_board, device=device).clamp(min=1e-5)
    n_up_a_t = torch.tensor(n_up_alight, device=device).clamp(min=1e-5)
    n_dn_b_t = torch.tensor(n_down_board, device=device).clamp(min=1e-5)
    n_dn_a_t = torch.tensor(n_down_alight, device=device).clamp(min=1e-5)

    idx_s = torch.tensor(all_s_idx, dtype=torch.long, device=device)
    idx_h = torch.tensor(all_h_idx, dtype=torch.long, device=device)
    t_dir = torch.tensor(all_dir, dtype=torch.float32, device=device)
    m_dest = torch.tensor(all_is_dest, dtype=torch.float32, device=device)
    m_orig = torch.tensor(all_is_orig, dtype=torch.float32, device=device)

    # 지리적 사전 확률(Prior)
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

    # 4) 빠른 최적화 (200 에포크)
    for _ in range(200):
        optimizer.zero_grad()
        p, q = get_full_pq()

        b_up_grid = (p * B_t) / n_up_b_t
        b_dn_grid = ((1.0 - p) * B_t) / n_dn_b_t
        a_up_grid = (q * A_t) / n_up_a_t
        a_dn_grid = ((1.0 - q) * A_t) / n_dn_a_t

        b_up_stops = b_up_grid[idx_s, idx_h] * (1.0 - m_dest)
        b_dn_stops = b_dn_grid[idx_s, idx_h] * (1.0 - m_dest)
        a_up_stops = a_up_grid[idx_s, idx_h] * (1.0 - m_orig)
        a_dn_stops = a_dn_grid[idx_s, idx_h] * (1.0 - m_orig)

        b_stops = (1.0 - t_dir) * b_up_stops + t_dir * b_dn_stops
        a_stops = (1.0 - t_dir) * a_up_stops + t_dir * a_dn_stops
        net_stops = b_stops - a_stops

        term_loads = []
        neg_penalties = []
        for st, en, _ in train_slices:
            train_net = net_stops[st:en]
            train_load = torch.cumsum(train_net, dim=0)
            term_loads.append(train_load[-1])
            neg_penalties.append(torch.relu(-train_load))

        term_tensor = torch.stack(term_loads)
        all_neg = torch.cat(neg_penalties)

        loss = torch.mean(term_tensor ** 2) + 1.0 * torch.mean(all_neg ** 2) + \
               2.0 * (torch.mean((torch.sigmoid(p_logits) - prior_p_t)**2) + \
                      torch.mean((torch.sigmoid(q_logits) - prior_q_t)**2))
        loss.backward()
        optimizer.step()

    # 5) 최종 재차인원 산출
    with torch.no_grad():
        p, q = get_full_pq()
        b_up_grid = (p * B_t) / n_up_b_t
        b_dn_grid = ((1.0 - p) * B_t) / n_dn_b_t
        a_up_grid = (q * A_t) / n_up_a_t
        a_dn_grid = ((1.0 - q) * A_t) / n_dn_a_t

        b_up_stops = (b_up_grid[idx_s, idx_h] * (1.0 - m_dest)).cpu().numpy()
        b_dn_stops = (b_dn_grid[idx_s, idx_h] * (1.0 - m_dest)).cpu().numpy()
        a_up_stops = (a_up_grid[idx_s, idx_h] * (1.0 - m_orig)).cpu().numpy()
        a_dn_stops = (a_dn_grid[idx_s, idx_h] * (1.0 - m_orig)).cpu().numpy()

        t_dir_np = t_dir.cpu().numpy()
        b_stops = (1.0 - t_dir_np) * b_up_stops + t_dir_np * b_dn_stops
        a_stops = (1.0 - t_dir_np) * a_up_stops + t_dir_np * a_dn_stops

    # 날씨 파싱
    weather_time_list = weather_raw["time"]
    records = []

    for st, en, _ in train_slices:
        train_b = b_stops[st:en]
        train_a = a_stops[st:en]
        
        # 물리적 누적 재차인원 계산 (음수 클램핑)
        current_load = 0.0
        for i, stop_idx in enumerate(range(st, en)):
            meta = stop_meta[stop_idx]
            b_val = float(train_b[i])
            a_val = float(train_a[i])
            current_load = max(0.0, current_load + b_val - a_val)

            # 종점에서는 승객이 모두 하차하므로 0으로 수렴
            if meta["is_destination"]:
                current_load = 0.0

            # 날씨 매칭
            w_h = 0 if meta["hour"] == 24 else meta["hour"]
            w_key = f"{date_str}T{w_h:02d}:00"
            try:
                w_idx = weather_time_list.index(w_key)
                precip = weather_raw["precipitation"][w_idx]
                snow = weather_raw["snowfall"][w_idx]
                temp = weather_raw["temperature_2m"][w_idx]
            except (ValueError, IndexError):
                precip, snow, temp = 0.0, 0.0, 15.0

            records.append({
                "date": date_str,
                "train_id": meta["train_id"],
                "direction": meta["direction"],
                "dir_code": meta["dir_code"],
                "day_type": day_type,
                "is_weekend": 1 if day_type == "휴일" else 0,
                "station": meta["station"],
                "station_idx": meta["station_idx"],
                "time": meta["time"],
                "hour": meta["hour"],
                "hour_idx": meta["hour_idx"],
                "is_origin": meta["is_origin"],
                "is_destination": meta["is_destination"],
                "board": round(b_val, 2),
                "alight": round(a_val, 2),
                "load": round(current_load, 2),
                "precip": precip,
                "snow": snow,
                "temp": temp,
                "plan_version": plan_version,
            })

    return records

# ==========================================
# 4. 메인 파이프라인
# ==========================================
def main():
    parser = argparse.ArgumentParser(description="열차 재차인원 정답 데이터셋 생성기")
    parser.add_argument("--start-date", type=str, default="2026-08-01", help="시작 날짜 (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, default="2026-10-31", help="종료 날짜 (YYYY-MM-DD)")
    parser.add_argument("--output", type=str, default="./outputs/ground_truth_train_loads.csv", help="출력 CSV 경로")
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"==================================================")
    print(f" [Ground Truth 생성기] Device: {device}")
    print(f" 기간: {args.start_date} ~ {args.end_date}")
    print(f" 출력: {args.output}")
    print(f"==================================================")

    start_dt = datetime.strptime(args.start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(args.end_date, "%Y-%m-%d")

    all_records = []
    curr = start_dt
    t0 = time.time()
    day_count = 0

    while curr <= end_dt:
        date_str = curr.strftime("%Y-%m-%d")
        next_date_str = (curr + timedelta(days=1)).strftime("%Y-%m-%d")

        subway_file = SUBWAY_DIR / f"{date_str}.json"
        next_subway_file = SUBWAY_DIR / f"{next_date_str}.json"
        weather_file = WEATHER_DIR / f"{date_str}.json"

        if not subway_file.exists() or not weather_file.exists():
            curr += timedelta(days=1)
            continue

        records = process_single_date(date_str, subway_file, next_subway_file, weather_file, device)
        all_records.extend(records)
        day_count += 1

        if day_count % 10 == 0 or curr == end_dt:
            elapsed = time.time() - t0
            print(f"진행: {date_str} ({day_count}일 완료, 누적 레코드: {len(all_records):,}건, 경과: {elapsed:.1f}초)")

        curr += timedelta(days=1)

    df = pd.DataFrame(all_records)
    df.to_csv(args.output, index=False, encoding="utf-8-sig")
    print(f"\n✅ 완료! 총 {day_count}일간 {len(df):,}개 정차역 레코드 생성됨.")
    print(f"저장 경로: {args.output}")

if __name__ == "__main__":
    main()
