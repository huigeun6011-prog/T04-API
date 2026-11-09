"""
train_load_model.py
대전 1호선 열차 재차인원 예측 모델 (최종 수정판)

수정 요약:
- HOURS = 5~24 (24 = 자정 넘김). 참조 파일(subway/{날짜}.json, subway_time)은
  00~04시를 '00'~'04' 키로 기록 → normalize_hour 로 24 버킷에 통합.
- 종점 재차 손실을 배치 단위 미분 가능 손실로 교체 (기존: no_grad 상수 → gradient 0).
- 물리 조건: 기점 승차 전 재차=0, 종점 하차 후 재차=0 (종점 승차 0, 하차는 예측값 그대로).
- CPU/GPU 별 autocast·GradScaler 분기, station_hourly/subway_time 캐시, 시드 고정.
"""

import json
import random
from datetime import datetime
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader

# ==========================================
# 0. 경로 및 상수
# ==========================================
SUBWAY_DIR = Path("./data/processed/subway")
WEATHER_DIR = Path("./data/raw/weather")
STATION_HOURLY_BEFORE = Path("./data/processed/subway_time/station_hourly_20250930.json")
STATION_HOURLY_AFTER = Path("./data/processed/subway_time/station_hourly_20260330.json")
SUBWAY_TIME_BEFORE = Path("./data/processed/subway_time/subway_time_20250930.json")
SUBWAY_TIME_AFTER = Path("./data/processed/subway_time/subway_time_20260330.json")
OUTPUT_DIR = Path("./outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PLAN_CHANGE_DATE = "2026-03-30"
TRAIN_END = "2026-07-31"
VAL_START = "2026-08-01"
VAL_END = "2026-11-01"

STATION_NAMES = ["판암","신흥","대동","대전","중앙로","중구청","서대전네거리","오룡",
                 "용문","탄방","시청","정부청사","갈마","월평","갑천","유성온천",
                 "구암","현충원","월드컵경기장","노은","지족","반석"]
STATION_TO_IDX = {name: i for i, name in enumerate(STATION_NAMES)}

# 5~24시 (24 = 자정 넘김 버킷)
HOURS = list(range(5, 25))          # 5,6,...,23,24
HOUR_TO_IDX = {h: i for i, h in enumerate(HOURS)}
N_HOURS = len(HOURS)

# ==========================================
# 재현성
# ==========================================
def set_seed(seed=42):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)

# ==========================================
# 0-1. 시간 정규화
# ==========================================
def normalize_hour(h):
    """
    참조 파일의 시각 표기 → 운행일 기준 hour (5~24).
    - 5~23  : 그대로
    - 0~4   : 24 로 통합 (자정 넘김, 참조 파일에는 '00'~'04' 로 기록됨)
    - 24    : 24 (혹시 '24:xx' 표기 대비)
    """
    if h == 24:
        return 24
    if 0 <= h <= 4:
        return 24
    return h   # 5~23

def normalize_hour_key(hour_key_str):
    """boardings/alightings 키('00'~'23')를 운행일 기준 hour 로 정규화."""
    h = int(hour_key_str)
    return normalize_hour(h)

def lookup_hour_value(hour_dict, hour):
    """
    원본 역·시간대 dict 에서 운행일 기준 hour(5~24)의 값을 조회.
    - 24 → '00'~'04' 키를 모두 합산 (자정 넘김 버킷)
    - 5~23 → 해당 키
    """
    total = 0
    for k, v in hour_dict.items():
        try:
            h = int(k)
        except ValueError:
            continue
        if normalize_hour(h) == hour:
            total += v
    return total

# ==========================================
# 1. 데이터 로드 (+ 캐시)
# ==========================================
def load_subway_data():
    data = {}
    for path in sorted(SUBWAY_DIR.glob("*.json")):
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        data[d["date"]] = d["stations"]
    return data

def load_weather_data():
    data = {}
    for path in sorted(WEATHER_DIR.glob("*.json")):
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        data[d["date"]] = d["hourly"]
    return data

_STATION_HOURLY_CACHE = {}
_SUBWAY_TIME_CACHE = {}

def load_station_hourly(date_str):
    if date_str in _STATION_HOURLY_CACHE:
        return _STATION_HOURLY_CACHE[date_str]
    path = STATION_HOURLY_AFTER if date_str >= PLAN_CHANGE_DATE else STATION_HOURLY_BEFORE
    with open(path, encoding="utf-8") as f:
        obj = json.load(f)
    _STATION_HOURLY_CACHE[date_str] = obj
    return obj

def load_subway_time(date_str):
    if date_str in _SUBWAY_TIME_CACHE:
        return _SUBWAY_TIME_CACHE[date_str]
    path = SUBWAY_TIME_AFTER if date_str >= PLAN_CHANGE_DATE else SUBWAY_TIME_BEFORE
    with open(path, encoding="utf-8") as f:
        obj = json.load(f)
    _SUBWAY_TIME_CACHE[date_str] = obj
    return obj

def get_day_type(date_str):
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return "휴일" if dt.weekday() >= 5 else "평일"

# ==========================================
# 2. 샘플 생성
# ==========================================
def build_samples(subway_data, weather_data):
    """
    샘플 = (날짜, 역, 시간대, 방향)
    라벨 = 원본 총승차/총하차 (방향 무관).
    시간대는 5~24 (24 = 자정 넘김, 원본의 '00'~'04' 합산).
    """
    samples = []
    for date_str, stations in subway_data.items():
        if date_str not in weather_data:
            continue
        weather = weather_data[date_str]
        day_type = get_day_type(date_str)
        plan_version = 1 if date_str >= PLAN_CHANGE_DATE else 0
        time_list = weather["time"]

        for sid_str, station_data in stations.items():
            sid = int(sid_str)
            if not (101 <= sid <= 122):
                continue
            station = STATION_NAMES[sid - 101]
            boardings = station_data.get("boardings", {})
            alightings = station_data.get("alightings", {})

            for h in HOURS:
                b = lookup_hour_value(boardings, h)
                a = lookup_hour_value(alightings, h)
                if b == 0 and a == 0:
                    continue

                # 날씨 시각: 24시 버킷은 자정 넘김이므로 다음날 '00'~'04' 중 대표값 사용
                # → 여기서는 24 버킷을 '00' 시각으로 조회 (없으면 skip)
                weather_hour = 0 if h == 24 else h
                w_key = f"{date_str}T{weather_hour:02d}:00"
                try:
                    w_idx = time_list.index(w_key)
                except ValueError:
                    continue
                precip = weather["precipitation"][w_idx]
                snow = weather["snowfall"][w_idx]
                temp = weather["temperature_2m"][w_idx]

                for direction in (0, 1):
                    samples.append({
                        "date": date_str,
                        "station": station,
                        "station_idx": STATION_TO_IDX[station],
                        "hour": h,
                        "hour_idx": HOUR_TO_IDX[h],
                        "direction": direction,
                        "is_weekend": 1 if day_type == "휴일" else 0,
                        "precip": precip,
                        "snow": snow,
                        "temp": temp,
                        "plan_version": plan_version,
                        "board_label": b,
                        "alight_label": a,
                    })
    return samples

# ==========================================
# 3. Dataset (인덱스도 반환 → terminal 손실용 샘플 복원)
# ==========================================
class SubwayDataset(Dataset):
    def __init__(self, samples):
        self.samples = samples
        X = np.array([[
            s["station_idx"], s["hour_idx"], s["direction"],
            s["is_weekend"], s["precip"], s["snow"], s["temp"], s["plan_version"],
        ] for s in samples], dtype=np.float32)
        Y = np.log1p(np.array([[
            s["board_label"], s["alight_label"],
        ] for s in samples], dtype=np.float32))
        self.X = torch.from_numpy(X)
        self.Y = torch.from_numpy(Y)

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        return self.X[idx], self.Y[idx], idx

# ==========================================
# 4. 모델
# ==========================================
class LoadPredictor(nn.Module):
    def __init__(self, n_stations=22, n_hours=N_HOURS, embed_dim=16, hidden=128):
        super().__init__()
        self.station_embed = nn.Embedding(n_stations, embed_dim)
        self.hour_embed = nn.Embedding(n_hours, embed_dim)
        input_dim = embed_dim * 2 + 2 + 3 + 1
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden),
            nn.ReLU(),
            nn.Linear(hidden, hidden),
            nn.ReLU(),
            nn.Linear(hidden, hidden),
            nn.ReLU(),
            nn.Linear(hidden, 2),
            nn.ReLU(),   # log1p 공간에서 음수 방지
        )

    def forward(self, x):
        station_idx = x[:, 0].long()
        hour_idx = x[:, 1].long()
        rest = x[:, 2:]
        emb = torch.cat([self.station_embed(station_idx), self.hour_embed(hour_idx)], dim=1)
        z = torch.cat([emb, rest], dim=1)
        return self.net(z)   # log1p 공간

# ==========================================
# 5. n_trains 룩업 (station_hourly 평탄화)
# ==========================================
def _build_n_train_lookup(date_str):
    """
    {(day_type, station, hour(5~24), direction): n_trains}
    station_hourly 의 hour 키('00'~'23')를 normalize_hour 로 5~24 로 통합.
    direction: 0=상행(departures+passes), 1=하행(passes+arrivals)
    """
    sh = load_station_hourly(date_str)
    lookup = defaultdict(int)
    for day_type, stations in sh.items():
        for station, hours in stations.items():
            for h_key, cell in hours.items():
                try:
                    h = normalize_hour(int(h_key))
                except ValueError:
                    continue
                lookup[(day_type, station, h, 0)] += cell.get("departures", 0) + cell.get("passes", 0)
                lookup[(day_type, station, h, 1)] += cell.get("passes", 0) + cell.get("arrivals", 0)
    return lookup

# ==========================================
# 6. 종점 재차 손실 (배치 단위, 미분 가능)
# ==========================================
def compute_terminal_loss_from_pred(pred, batch_samples, device):
    """
    pred: (B, 2) log1p 공간 예측 텐서 (grad 유지).
    물리:
      - 기점 승차 전 재차 = 0 (load 초기값)
      - 종점: 승차 0, 하차는 예측값 그대로 → 종점 하차 후 재차 = load (0 목표)
    반환: |종점 하차 후 재차| 평균 (스칼라 텐서, grad 유지)
    """
    pred_raw = torch.clamp(torch.expm1(pred), min=0.0)   # (B,2)

    key_to_indices = defaultdict(list)
    for i, s in enumerate(batch_samples):
        key_to_indices[(s["date"], s["station"], s["hour"])].append(i)

    date_to_keys = defaultdict(list)
    for key in key_to_indices:
        date_to_keys[key[0]].append(key)

    n_train_cache = {}
    abs_loads = []

    for date_str, keys in date_to_keys.items():
        subway_time = load_subway_time(date_str)
        day_type = get_day_type(date_str)
        if date_str not in n_train_cache:
            n_train_cache[date_str] = _build_n_train_lookup(date_str)
        n_lookup = n_train_cache[date_str]

        for direction_name, dir_code in (("상행", 0), ("하행", 1)):
            for train in subway_time["trains"]:
                if train["direction"] != direction_name or train["day_type"] != day_type:
                    continue
                load = torch.zeros((), device=device)     # 기점 승차 전 = 0
                stops = train["stops"]
                n_stops = len(stops)
                for idx, stop in enumerate(stops):
                    station = stop["station"]
                    hour = normalize_hour(int(stop["time"].split(":")[0]))
                    key = (date_str, station, hour)
                    if key not in key_to_indices:
                        continue
                    for i in key_to_indices[key]:
                        s = batch_samples[i]
                        if s["direction"] != dir_code:
                            continue
                        n_trains = n_lookup.get((day_type, station, hour, dir_code), 0)
                        if n_trains == 0:
                            continue
                        b_share = pred_raw[i, 0] / n_trains
                        a_share = pred_raw[i, 1] / n_trains
                        if idx == 0:
                            a_share = torch.zeros((), device=device)   # 기점 하차 없음
                        if idx == n_stops - 1:
                            b_share = torch.zeros((), device=device)   # 종점 승차 없음
                        load = load - a_share + b_share
                abs_loads.append(torch.abs(load))

    if not abs_loads:
        return torch.zeros((), device=device, requires_grad=True)
    return torch.stack(abs_loads).mean()

# ==========================================
# 7. 검증용 종점 재차 MAE (no_grad 모니터링)
# ==========================================
@torch.no_grad()
def compute_terminal_mae_monitor(model, val_samples, device, batch_size=2048):
    model.eval()
    pred_raw_all = []
    loader = DataLoader(SubwayDataset(val_samples), batch_size=batch_size,
                        shuffle=False, num_workers=0)
    for x, _, _ in loader:
        p = model(x.to(device))
        pred_raw_all.append(torch.clamp(torch.expm1(p), min=0.0).cpu())
    pred_raw_all = torch.cat(pred_raw_all, dim=0).numpy()

    pred_map = defaultdict(dict)
    for i, s in enumerate(val_samples):
        pred_map[(s["date"], s["station"], s["hour"])][s["direction"]] = pred_raw_all[i]

    abs_loads = []
    for date_str in sorted(set(s["date"] for s in val_samples)):
        subway_time = load_subway_time(date_str)
        day_type = get_day_type(date_str)
        n_lookup = _build_n_train_lookup(date_str)

        for direction_name, dir_code in (("상행", 0), ("하행", 1)):
            for train in subway_time["trains"]:
                if train["direction"] != direction_name or train["day_type"] != day_type:
                    continue
                load = 0.0
                stops = train["stops"]
                n_stops = len(stops)
                for idx, stop in enumerate(stops):
                    station = stop["station"]
                    hour = normalize_hour(int(stop["time"].split(":")[0]))
                    key = (date_str, station, hour)
                    if key not in pred_map or dir_code not in pred_map[key]:
                        continue
                    n_trains = n_lookup.get((day_type, station, hour, dir_code), 0)
                    if n_trains == 0:
                        continue
                    b, a = pred_map[key][dir_code]
                    b_share, a_share = b / n_trains, a / n_trains
                    if idx == 0:
                        a_share = 0.0
                    if idx == n_stops - 1:
                        b_share = 0.0
                    load += -a_share + b_share
                abs_loads.append(abs(load))
    return float(np.mean(abs_loads)) if abs_loads else 0.0

# ==========================================
# 8. 학습
# ==========================================
def train():
    set_seed(42)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    use_amp = device.type == "cuda"
    print(f"Device: {device}, AMP: {use_amp}")

    print("데이터 로드 중...")
    subway_data = load_subway_data()
    weather_data = load_weather_data()
    print(f"  지하철: {len(subway_data)}일, 날씨: {len(weather_data)}일")

    print("샘플 생성 중...")
    all_samples = build_samples(subway_data, weather_data)
    print(f"  총 샘플: {len(all_samples):,}")

    train_samples = [s for s in all_samples if s["date"] <= TRAIN_END]
    val_samples = [s for s in all_samples if VAL_START <= s["date"] <= VAL_END]
    print(f"  학습: {len(train_samples):,}, 검증: {len(val_samples):,}")

    train_ds = SubwayDataset(train_samples)
    train_loader = DataLoader(
        train_ds, batch_size=1024, shuffle=True, num_workers=4,
        pin_memory=use_amp, persistent_workers=False,
        generator=torch.Generator().manual_seed(42),
    )

    model = LoadPredictor().to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    scaler = torch.amp.GradScaler("cuda") if use_amp else None
    mse_loss = nn.MSELoss()

    def elastic_net_loss(m, l1=1e-5, l2=1e-4):
        s1, s2 = 0.0, 0.0
        for p in m.parameters():
            s1 = s1 + p.abs().sum()
            s2 = s2 + (p ** 2).sum()
        return l1 * s1 + l2 * s2

    def forward(x):
        if use_amp:
            with torch.amp.autocast("cuda", dtype=torch.float16):
                return model(x)
        return model(x)

    best_val = float("inf")
    patience, pc = 15, 0
    max_epochs = 200
    terminal_weight = 0.05

    # 초기 모니터링
    init_mae = compute_terminal_mae_monitor(model, val_samples, device)
    print(f"초기 terminal_mae: {init_mae:.4f}")

    for epoch in range(max_epochs):
        # ===== 학습 =====
        model.train()
        tr_sum, n = 0.0, 0
        for x, y, idxs in train_loader:
            x, y = x.to(device), y.to(device)
            batch_samples = [train_ds.samples[i] for i in idxs.tolist()]

            optimizer.zero_grad()
            pred = forward(x)                                   # autocast 안: Half
            loss_mse = mse_loss(pred.float(), y.float())        # MSE는 float32로
            loss_en = elastic_net_loss(model)

            # terminal 손실은 float32로 재계산 (pred_raw만 다시 뽑음)
            with torch.amp.autocast("cuda", enabled=False):
                pred_f32 = model(x.float()) if use_amp else pred
                loss_term = compute_terminal_loss_from_pred(pred_f32.float(), batch_samples, device)

            loss = loss_mse + loss_en + terminal_weight * loss_term

            if use_amp:
                scaler.scale(loss).backward()
                scaler.step(optimizer)
                scaler.update()
            else:
                loss.backward()
                optimizer.step()
            tr_sum += loss.item() * x.size(0)
            n += x.size(0)
        tr_loss = tr_sum / n

        # ===== 검증 =====
        model.eval()
        v_sum, vn = 0.0, 0
        val_loader = DataLoader(SubwayDataset(val_samples), batch_size=2048,
                                shuffle=False, num_workers=0)
        with torch.no_grad():
            for x, y, _ in val_loader:
                x, y = x.to(device), y.to(device)
                pred = forward(x)
                v_sum += mse_loss(pred, y).item() * x.size(0)
                vn += x.size(0)
        v_loss = v_sum / vn

        # ===== 종점 재차 MAE (모니터링) =====
        MONITOR_EVERY = 5
        if (epoch + 1) % MONITOR_EVERY == 0:
            last_t_mae = compute_terminal_mae_monitor(model, val_samples, device)
        t_mae = last_t_mae
        total = v_loss + terminal_weight * t_mae
        print(f"Epoch {epoch+1:3d} | train={tr_loss:.4f} | val={v_loss:.4f} "
              f"| term_mae={t_mae:.4f} | total={total:.4f}")

        # ===== 조기 종료 =====
        if total < best_val - 1e-5:
            best_val = total
            pc = 0
            torch.save(model.state_dict(), OUTPUT_DIR / "best_model.pt")
        else:
            pc += 1
            if pc >= patience:
                print(f"조기 종료 (patience={patience})")
                break

    print(f"\n학습 완료. 최적 검증 손실: {best_val:.4f}")
    print(f"모델 저장: {OUTPUT_DIR / 'best_model.pt'}")

if __name__ == "__main__":
    train()