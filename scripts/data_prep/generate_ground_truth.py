"""
generate_ground_truth.py
과거 승하차 데이터와 시각표, 날씨 데이터를 결합하고,
종점 잔여 및 음수 누적 재차인원에 soft penalty를 주는 최적화를 수행하여
열차별/역별 추정 재차인원 라벨을 생성합니다. 물리 제약 충족을 보장하지
않으며, raw_load/보정량 및 배분 불가능한 관측 총량을 별도로 보존합니다.
"""

import os
import sys
import json
import argparse
import time
import csv
from functools import partial
from concurrent.futures import ProcessPoolExecutor

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
try:
    from .gt_assumptions import AssumptionConfig, boarding_exposures, WeekdayTemplates
except ImportError:
    from gt_assumptions import AssumptionConfig, boarding_exposures, WeekdayTemplates

# ==========================================
# 1. 상수 정의
# ==========================================
ROOT = Path(__file__).resolve().parents[2]
SUBWAY_DIR = ROOT / "data/processed/subway"
WEATHER_DIR = ROOT / "data/raw/weather"
SUBWAY_TIME_BEFORE = ROOT / "data/processed/subway_time/subway_time_20250930.json"
SUBWAY_TIME_AFTER = ROOT / "data/processed/subway_time/subway_time_20260330.json"
OUTPUT_DIR = ROOT / "outputs"
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
    if h in (0, 24):
        return 24
    if not 5 <= h <= 23:
        raise ValueError(f"운행 시간대가 아닙니다: {h}")
    return h

def get_day_type(date_str):
    if date_str in HOLIDAYS:
        return "휴일"
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return "휴일" if dt.weekday() >= 5 else "평일"


def feasible_shares(up_share, up_count, down_count):
    """Keep the learned split only where both directions can carry passengers.

    A single feasible direction receives the full observation. If neither is
    feasible, both shares are zero and the observation stays explicit slack.
    """
    up_ok, down_ok = up_count > 0, down_count > 0
    up_weight = torch.where(up_ok, torch.where(down_ok, up_share, 1.0), 0.0)
    down_weight = torch.where(down_ok, torch.where(up_ok, 1.0-up_share, 1.0), 0.0)
    return up_weight, down_weight

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
def process_single_date(date_str, subway_file, next_subway_file, weather_file, device,
                        epochs=1000, patience=100, min_epochs=200, init_seed=None,
                        diagnostics=None, assumptions=None, weekday_template=None,
                        capture_ratios=False):
    assumptions = assumptions or AssumptionConfig()
    if assumptions.pooling_weight and weekday_template is None:
        raise ValueError("요일 pooling에는 과거 날짜로 fit한 template snapshot이 필요합니다.")
    with open(subway_file, encoding="utf-8") as f:
        curr_subway = json.load(f)
    
    next_subway = None
    if next_subway_file and os.path.exists(next_subway_file):
        with open(next_subway_file, encoding="utf-8") as f:
            next_subway = json.load(f)
            
    with open(weather_file, encoding="utf-8") as f:
        weather_raw = json.load(f)["hourly"]
    next_date = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    with open(WEATHER_DIR / f"{next_date}.json", encoding="utf-8") as f:
        next_weather = json.load(f)["hourly"]
    weather_lookup = {}
    for hourly in (weather_raw, next_weather):
        for i, stamp in enumerate(hourly["time"]):
            weather_lookup[stamp] = tuple(hourly[key][i] for key in ("precipitation", "snowfall", "temperature_2m"))

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
    n_up_b_t = torch.tensor(n_up_board, device=device)
    n_up_a_t = torch.tensor(n_up_alight, device=device)
    n_dn_b_t = torch.tensor(n_down_board, device=device)
    n_dn_a_t = torch.tensor(n_down_alight, device=device)

    idx_s = torch.tensor(all_s_idx, dtype=torch.long, device=device)
    idx_h = torch.tensor(all_h_idx, dtype=torch.long, device=device)
    t_dir = torch.tensor(all_dir, dtype=torch.float32, device=device)
    m_dest = torch.tensor(all_is_dest, dtype=torch.float32, device=device)
    m_orig = torch.tensor(all_is_orig, dtype=torch.float32, device=device)
    exposure_edges = []
    boarding_coverage = None
    both_coverage = None
    if assumptions.boarding_headway:
        exposure_edges, boarding_coverage, both_coverage = boarding_exposures(stop_meta)
        edge_array = np.asarray(exposure_edges, dtype=np.float64)
        edge_stop = torch.tensor(edge_array[:,0], dtype=torch.long, device=device)
        edge_station = torch.tensor(edge_array[:,1], dtype=torch.long, device=device)
        edge_hour = torch.tensor(edge_array[:,2], dtype=torch.long, device=device)
        edge_direction = torch.tensor(edge_array[:,3], dtype=torch.float32, device=device)
        edge_both = torch.tensor(edge_array[:,4], dtype=torch.float32, device=device)
        edge_only = torch.tensor(edge_array[:,5], dtype=torch.float32, device=device)

    def boardings_at_stops(p, b_up_grid, b_dn_grid):
        if assumptions.boarding_headway:
            edge_up_share = p[edge_station,edge_hour]
            edge_share = (1-edge_direction)*edge_up_share+edge_direction*(1-edge_up_share)
            amounts = B_t[edge_station,edge_hour]*(edge_share*edge_both+edge_only)
            return torch.zeros_like(t_dir).scatter_add(0,edge_stop,amounts), amounts
        up = b_up_grid[idx_s,idx_h]*(1-m_dest)
        down = b_dn_grid[idx_s,idx_h]*(1-m_dest)
        return (1-t_dir)*up+t_dir*down, None

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
    if init_seed is not None:
        rng = np.random.default_rng(init_seed)
        p_logit_init += rng.normal(0, .25, p_logit_init.shape).astype(np.float32)
        q_logit_init += rng.normal(0, .25, q_logit_init.shape).astype(np.float32)

    p_logits = torch.nn.Parameter(torch.tensor(p_logit_init, device=device))
    q_logits = torch.nn.Parameter(torch.tensor(q_logit_init, device=device))

    prior_p_t = torch.tensor(p_prior[1:-1, :], device=device)
    prior_q_t = torch.tensor(q_prior[1:-1, :], device=device)

    optimizer = torch.optim.Adam([p_logits, q_logits], lr=0.1)

    # Each row is one train. Padding avoids hundreds of tiny autograd operations
    # per epoch while keeping exactly the same terminal/negative-load objective.
    lengths = torch.tensor([en - st for st, en, _ in train_slices], device=device)
    offsets = torch.arange(int(lengths.max()), device=device)[None, :]
    starts = torch.tensor([st for st, _, _ in train_slices], device=device)[:, None]
    valid = offsets < lengths[:, None]
    gather_idx = (starts + offsets).clamp(max=len(all_s_idx) - 1)

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

    def split_grids(p, q):
        p_up, p_down = feasible_shares(p, n_up_b_t, n_dn_b_t)
        q_up, q_down = feasible_shares(q, n_up_a_t, n_dn_a_t)
        return (p_up*B_t/n_up_b_t.clamp(min=1),
                p_down*B_t/n_dn_b_t.clamp(min=1),
                q_up*A_t/n_up_a_t.clamp(min=1),
                q_down*A_t/n_dn_a_t.clamp(min=1))

    # Unidentifiable split parameters (only one/no direction) must not pull the
    # solver toward an arbitrary geography split that cannot allocate counts.
    p_identified = (torch.tensor(both_coverage > 0,device=device)[1:-1]
                    if assumptions.boarding_headway else ((n_up_b_t > 0) & (n_dn_b_t > 0))[1:-1])
    q_identified = ((n_up_a_t > 0) & (n_dn_a_t > 0))[1:-1]

    def prior_loss():
        p_delta = (torch.sigmoid(p_logits)-prior_p_t)**2
        q_delta = (torch.sigmoid(q_logits)-prior_q_t)**2
        return ((p_delta*p_identified).sum()/p_identified.sum().clamp(min=1)
                +(q_delta*q_identified).sum()/q_identified.sum().clamp(min=1))

    p_reg_mask = p_identified & (B_t[1:-1]>0)
    q_reg_mask = q_identified & (A_t[1:-1]>0)
    if weekday_template is not None:
        p_target = torch.tensor(weekday_template["p"][1:-1],device=device)
        q_target = torch.tensor(weekday_template["q"][1:-1],device=device)
        p_confidence = torch.tensor(weekday_template["p_confidence"][1:-1],device=device)*p_reg_mask
        q_confidence = torch.tensor(weekday_template["q_confidence"][1:-1],device=device)*q_reg_mask

    def structural_losses(p,q):
        smooth = p.sum()*0
        if assumptions.temporal_weight:
            for value,mask in ((p[1:-1],p_reg_mask),(q[1:-1],q_reg_mask)):
                difference=value[:,1:]-value[:,:-1]
                neighbors=mask[:,1:]&mask[:,:-1]
                penalty=torch.nn.functional.huber_loss(difference,torch.zeros_like(difference),delta=assumptions.temporal_huber_delta,reduction="none")
                smooth=smooth+(penalty*neighbors).sum()/neighbors.sum().clamp(min=1)
        pooled = p.sum()*0
        if assumptions.pooling_weight:
            for value,target,confidence in ((p[1:-1],p_target,p_confidence),(q[1:-1],q_target,q_confidence)):
                # Divide by identified cells; low-data templates receive less
                # weight via confidence rather than forcing a shared ratio.
                pooled=pooled+(((value-target)**2)*confidence).sum()/(confidence>0).sum().clamp(min=1)
        return smooth*assumptions.temporal_weight, pooled*assumptions.pooling_weight

    # Terminal zero and nonnegative trajectories remain soft penalties.
    # Save the best iterate instead of publishing a later Adam oscillation.
    best_loss = float("inf")
    significant_best = float("inf")
    last_significant_epoch = 0
    best_epoch = 0
    best_parameters = None
    loss_history = []
    for epoch in range(epochs):
        optimizer.zero_grad()
        p, q = get_full_pq()

        b_up_grid, b_dn_grid, a_up_grid, a_dn_grid = split_grids(p, q)

        a_up_stops = a_up_grid[idx_s, idx_h] * (1.0 - m_orig)
        a_dn_stops = a_dn_grid[idx_s, idx_h] * (1.0 - m_orig)

        b_stops, _ = boardings_at_stops(p,b_up_grid,b_dn_grid)
        a_stops = (1.0 - t_dir) * a_up_stops + t_dir * a_dn_stops
        net_stops = b_stops - a_stops

        train_load = torch.cumsum(net_stops[gather_idx] * valid, dim=1)
        term_tensor = train_load.gather(1, (lengths - 1)[:, None]).squeeze(1)
        all_neg = torch.relu(-train_load[valid])

        smooth_loss, pooled_loss = structural_losses(p,q)
        loss = torch.mean(term_tensor ** 2) + torch.mean(all_neg ** 2) + 2.0*prior_loss()+smooth_loss+pooled_loss
        current_loss = float(loss.detach())
        loss_history.append(current_loss)
        if current_loss < best_loss:
            best_loss = current_loss
            best_epoch = epoch+1
            best_parameters = (p_logits.detach().clone(), q_logits.detach().clone())
        if significant_best-current_loss > max(1e-5, abs(significant_best)*1e-5) or epoch == 0:
            significant_best = current_loss
            last_significant_epoch = epoch
        if patience and epoch+1 >= min_epochs and epoch-last_significant_epoch >= patience:
            break
        loss.backward()
        optimizer.step()

    # 5) 최종 재차인원 산출
    with torch.no_grad():
        p_logits.copy_(best_parameters[0])
        q_logits.copy_(best_parameters[1])
        p, q = get_full_pq()
        b_up_grid, b_dn_grid, a_up_grid, a_dn_grid = split_grids(p, q)

        a_up_stops = (a_up_grid[idx_s, idx_h] * (1.0 - m_orig)).cpu().numpy()
        a_dn_stops = (a_dn_grid[idx_s, idx_h] * (1.0 - m_orig)).cpu().numpy()

        t_dir_np = t_dir.cpu().numpy()
        b_tensor, edge_amounts = boardings_at_stops(p,b_up_grid,b_dn_grid)
        b_stops = b_tensor.cpu().numpy()
        a_stops = (1.0 - t_dir_np) * a_up_stops + t_dir_np * a_dn_stops

    board_sources = None
    if assumptions.boarding_headway:
        board_sources = [[] for _ in stop_meta]
        # Accumulate final provenance in float64 so the emitted boarding amount
        # agrees with its source-hour components, not float32 scatter rounding.
        b_stops = np.zeros(len(stop_meta),dtype=np.float64)
        np.add.at(b_stops,np.asarray(exposure_edges)[:,0].astype(int),edge_amounts.cpu().numpy().astype(np.float64))
        for edge,amount in zip(exposure_edges,edge_amounts.cpu().numpy()):
            if amount:
                board_sources[edge[0]].append([HOURS[edge[2]],round(float(amount),6)])

    raw_paths = [np.cumsum(b_stops[st:en].astype(np.float64)-a_stops[st:en].astype(np.float64))
                 for st, en, _ in train_slices]
    terminal_raw = np.array([path[-1] for path in raw_paths])
    all_raw = np.concatenate(raw_paths)
    slack_rows = []
    for kind, observed, up_count, down_count in (
            ("board", B_obs, n_up_board, n_down_board),
            ("alight", A_obs, n_up_alight, n_down_alight)):
        unallocated = (observed*(1-boarding_coverage) if kind=="board" and assumptions.boarding_headway
                       else observed*((up_count+down_count)==0))
        for s_idx, h_idx in np.argwhere(unallocated > 0):
            slack_rows.append({"date": date_str, "station_idx": int(s_idx),
                               "station": STATION_NAMES[s_idx], "hour": HOURS[h_idx],
                               "kind": kind, "observed": float(observed[s_idx, h_idx]),
                               "unallocated": float(unallocated[s_idx,h_idx]),
                               "reason": ("uniform_arrival_after_last_eligible_departure" if kind=="board" and assumptions.boarding_headway else "no_eligible_train_stop_in_either_direction")})
    if diagnostics is not None:
        diagnostics.update({
            "date": date_str, "epochs_run": len(loss_history), "best_epoch": best_epoch,
            "best_loss": best_loss, "last_loss": loss_history[-1],
            "terminal_loss": float(np.mean(terminal_raw**2)),
            "negative_loss": float(np.mean(np.minimum(all_raw, 0)**2)),
            "prior_loss_weighted": float(2*prior_loss().detach()),
            "temporal_loss_weighted": float(structural_losses(p,q)[0].detach()),
            "pooling_loss_weighted": float(structural_losses(p,q)[1].detach()),
            "assumptions": {"temporal_weight": assumptions.temporal_weight,"temporal_huber_delta": assumptions.temporal_huber_delta,"pooling_weight":assumptions.pooling_weight,"boarding_headway":assumptions.boarding_headway},
            "template": ({key:weekday_template[key] for key in ("n_dates","last_training_date","group","window_days","source_sha256")} if weekday_template is not None else None),
            "n_date_parameters": int(p_logits.numel()+q_logits.numel()),
            "terminal_abs_quantiles": {str(q): float(np.quantile(np.abs(terminal_raw), q)) for q in (.5,.9,.95,.99,1)},
            "negative_raw_stops": int((all_raw < -.015).sum()),
            "raw_load_min": float(all_raw.min()),
            "nonnegative_projection_count": int((all_raw < 0).sum()),
            "nonnegative_projection_total": float(-np.minimum(all_raw, 0).sum()),
            "board_observed_total": float(B_obs.sum()),
            "alight_observed_total": float(A_obs.sum()),
            "board_allocated_total": float(b_stops.astype(np.float64).sum()),
            "alight_allocated_total": float(a_stops.astype(np.float64).sum()),
            "unallocated": slack_rows,
            "label_policy": "load=max(raw cumulative board-alight,0); origin preboarding=0; no terminal overwrite; raw_load and load_correction retained",
        })
        if capture_ratios:
            diagnostics["p_values"] = p.detach().cpu().numpy().tolist()
            diagnostics["q_values"] = q.detach().cpu().numpy().tolist()

    # 날씨 파싱
    weather_time_list = weather_raw["time"]
    records = []

    for st, en, _ in train_slices:
        train_b = b_stops[st:en]
        train_a = a_stops[st:en]
        
        # Preserve the optimizer trajectory; projection is explicit per row.
        # Terminal zero is a soft objective, never a hidden overwrite.
        raw_load = 0.0
        for i, stop_idx in enumerate(range(st, en)):
            meta = stop_meta[stop_idx]
            b_val = float(train_b[i])
            a_val = float(train_a[i])
            raw_load += b_val-a_val
            current_load = max(0.0, raw_load)

            # 날씨 매칭
            w_h = 0 if meta["hour"] == 24 else meta["hour"]
            weather_date = next_date if meta["hour"] == 24 else date_str
            w_key = f"{weather_date}T{w_h:02d}:00"
            if w_key not in weather_lookup:
                raise ValueError(f"날씨 자료가 없습니다: {w_key}")
            precip, snow, temp = weather_lookup[w_key]

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
                "board": round(b_val, 6),
                "alight": round(a_val, 6),
                "raw_load": round(raw_load, 6),
                "load_correction": round(current_load-raw_load, 6),
                "terminal_raw_residual": round(raw_load, 6) if meta["is_destination"] else None,
                "load": round(current_load, 6),
                "precip": precip,
                "snow": snow,
                "temp": temp,
                "plan_version": plan_version,
            })
            if board_sources is not None:
                records[-1]["boarding_sources"] = json.dumps(board_sources[stop_idx],separators=(",",":"))

    return records

# ==========================================
# 4. 메인 파이프라인
# ==========================================
_TEMPLATE_BANKS = {}


def process_service_day(date_str, epochs=1000, patience=100, assumptions=None,
                        template_bank=None, template_fit_through=None):
    torch.set_num_threads(1)
    next_date = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    diagnostics = {}
    snapshot = None
    if assumptions is not None and assumptions.pooling_weight:
        bank_key = str(template_bank)
        if bank_key not in _TEMPLATE_BANKS:
            _TEMPLATE_BANKS[bank_key] = WeekdayTemplates.load(template_bank)
        snapshot = _TEMPLATE_BANKS[bank_key].snapshot(date_str,HOLIDAYS,fit_through=template_fit_through)
    records = process_single_date(date_str, SUBWAY_DIR / f"{date_str}.json", SUBWAY_DIR / f"{next_date}.json", WEATHER_DIR / f"{date_str}.json", torch.device("cpu"), epochs=epochs, patience=patience, diagnostics=diagnostics, assumptions=assumptions, weekday_template=snapshot)
    return records, diagnostics

def main():
    parser = argparse.ArgumentParser(description="열차 재차인원 정답 데이터셋 생성기")
    parser.add_argument("--start-date", type=str, default="2024-11-01", help="시작 운행일 (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, default="2026-11-01", help="종료 운행일 (익일 00시 포함)")
    parser.add_argument("--output", type=str, default="./outputs/ground_truth_train_loads.csv", help="출력 CSV 경로")
    parser.add_argument("--workers", type=int, default=4, help="독립 운행일을 처리할 CPU 프로세스 수")
    parser.add_argument("--epochs", type=int, default=1000, help="최대 Adam 반복 수")
    parser.add_argument("--patience", type=int, default=100, help="개선 정체시 중단할 반복 수 (0=비활성)")
    parser.add_argument("--temporal-weight",type=float,default=0,help="인접시간 p/q Huber soft penalty 가중치")
    parser.add_argument("--temporal-huber-delta",type=float,default=.15)
    parser.add_argument("--pooling-weight",type=float,default=0,help="과거 동요일 template partial-pooling 가중치")
    parser.add_argument("--boarding-headway",action="store_true",help="시간 내 균등입장 가정과 시간표 이전출발간격을 이용한 승차 배분")
    parser.add_argument("--template-bank",type=Path,help="과거 독립일자 분배율 관측 npz")
    parser.add_argument("--template-fit-through",help="template에 허용할 마지막 학습일 (검증일 누수 방지)")
    args = parser.parse_args()
    if args.epochs < 1 or args.patience < 0 or args.workers < 1:
        parser.error("epochs/workers는 양수, patience는 0 이상이어야 합니다.")
    if args.temporal_weight<0 or args.pooling_weight<0 or args.temporal_huber_delta<=0:
        parser.error("soft penalty 가중치는 0 이상, Huber delta는 양수여야 합니다.")
    if args.pooling_weight and not args.template_bank:
        parser.error("pooling에는 --template-bank가 필요합니다.")
    assumptions=AssumptionConfig(args.temporal_weight,args.temporal_huber_delta,args.pooling_weight,args.boarding_headway)
    if args.epochs < 1 or args.patience < 0 or args.workers < 1:
        parser.error("epochs/workers는 1 이상, patience는 0 이상이어야 합니다.")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    torch.set_num_threads(1)
    print(f"==================================================")
    print(f" [Ground Truth 생성기] Device: {device}")
    print(f" 기간: {args.start_date} ~ {args.end_date}")
    print(f" 출력: {args.output}")
    print(f"==================================================")

    start_dt = datetime.strptime(args.start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(args.end_date, "%Y-%m-%d")

    dates = []
    curr = start_dt
    t0 = time.time()
    day_count = 0

    while curr <= end_dt:
        date_str = curr.strftime("%Y-%m-%d")
        next_date_str = (curr + timedelta(days=1)).strftime("%Y-%m-%d")

        subway_file = SUBWAY_DIR / f"{date_str}.json"
        next_subway_file = SUBWAY_DIR / f"{next_date_str}.json"
        weather_file = WEATHER_DIR / f"{date_str}.json"

        for required in (subway_file, next_subway_file, weather_file, WEATHER_DIR / f"{next_date_str}.json"):
            if not required.exists():
                raise FileNotFoundError(f"운행일 {date_str} 생성에 필요한 파일이 없습니다: {required}")

        dates.append(date_str)
        curr += timedelta(days=1)
    if not dates:
        raise ValueError("시작 운행일은 종료 운행일보다 늦을 수 없습니다.")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".partial.csv")
    total = 0
    diagnostic_path = output.with_suffix(".diagnostics.jsonl")
    slack_path = output.with_suffix(".unallocated.csv")
    with ProcessPoolExecutor(max_workers=max(1, args.workers)) as executor, temporary.open("w", encoding="utf-8-sig", newline="") as stream, diagnostic_path.open("w", encoding="utf-8") as diagnostic_stream, slack_path.open("w", encoding="utf-8-sig", newline="") as slack_stream:
        writer = None
        slack_writer = csv.DictWriter(slack_stream, fieldnames=["date","station_idx","station","hour","kind","observed","unallocated","reason"])
        slack_writer.writeheader()
        worker = partial(process_service_day, epochs=args.epochs, patience=args.patience,assumptions=assumptions,template_bank=args.template_bank,template_fit_through=args.template_fit_through)
        for date_str, (records, diagnostics) in zip(dates, executor.map(worker, dates)):
            if not records:
                raise ValueError(f"열차 표본이 없습니다: {date_str}")
            if writer is None:
                writer = csv.DictWriter(stream, fieldnames=list(records[0]))
                writer.writeheader()
            writer.writerows(records)
            slack_writer.writerows(diagnostics.pop("unallocated"))
            diagnostic_stream.write(json.dumps(diagnostics, ensure_ascii=False)+"\n")
            total += len(records)
            day_count += 1
            if day_count % 10 == 0 or day_count == len(dates):
                stream.flush()
                elapsed = time.time() - t0
                print(f"진행: {date_str} ({day_count}/{len(dates)}일, {total:,}행, {elapsed:.1f}초)", flush=True)
    temporary.replace(output)
    print(f"\n✅ 완료! 총 {day_count}일간 {total:,}개 정차역 레코드 생성됨.")
    print(f"저장 경로: {args.output}")

if __name__ == "__main__":
    main()
