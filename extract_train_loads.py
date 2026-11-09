"""
extract_train_loads.py
학습된 모델(load_predictor.joblib), 열차 운행 시각표(subway_time), 날씨 및 날짜 정보를 바탕으로
지정된 날짜(또는 기간)에 운행하는 모든 열차의 정차역별 재차인원 궤적(Trajectory)을 일괄 추출하여 JSON/CSV로 저장합니다.

사용법:
  # 1. 특정 단일 날짜 추출 (기본: ./outputs/train_loads/train_load_YYYY-MM-DD.json)
  python extract_train_loads.py --date 2025-11-04

  # 2. 날짜 범위 일괄 추출
  python extract_train_loads.py --start-date 2026-10-01 --end-date 2026-10-07

  # 3. CSV 형식으로도 함께 저장
  python extract_train_loads.py --date 2025-11-04 --save-csv
"""

import os
import sys
import json
import argparse
import time
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

import numpy as np
import pandas as pd
import joblib

# ==========================================
# 1. 경로 및 상수
# ==========================================
DEFAULT_MODEL_PATH = Path("./outputs/load_predictor.joblib")
WEATHER_DIR = Path("./data/raw/weather")
SUBWAY_DIR = Path("./data/processed/subway")
SUBWAY_TIME_BEFORE = Path("./data/processed/subway_time/subway_time_20250930.json")
SUBWAY_TIME_AFTER = Path("./data/processed/subway_time/subway_time_20260330.json")
DEFAULT_OUTPUT_DIR = Path("./outputs/train_loads")

PLAN_CHANGE_DATE = "2026-03-30"

STATION_NAMES = [
    "판암","신흥","대동","대전","중앙로","중구청","서대전네거리","오룡",
    "용문","탄방","시청","정부청사","갈마","월평","갑천","유성온천",
    "구암","현충원","월드컵경기장","노은","지족","반석"
]
STATION_TO_IDX = {name: i for i, name in enumerate(STATION_NAMES)}
N_STATIONS = len(STATION_NAMES)

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
# 2. 보조 함수
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

def get_congestion_level(load):
    if load < 80:
        return "여유"
    elif load < 180:
        return "보통"
    elif load < 300:
        return "약간 혼잡"
    elif load < 450:
        return "혼잡"
    else:
        return "매우 혼잡"

_TIME_CACHE = {}

def load_subway_schedule(date_str, day_type):
    """2026-03-30 시각표 개편 및 휴일 폴백 반영 시각표 로드"""
    if "before" not in _TIME_CACHE:
        with open(SUBWAY_TIME_BEFORE, encoding="utf-8") as f:
            _TIME_CACHE["before"] = json.load(f)
    if "after" not in _TIME_CACHE:
        with open(SUBWAY_TIME_AFTER, encoding="utf-8") as f:
            _TIME_CACHE["after"] = json.load(f)

    if date_str >= PLAN_CHANGE_DATE and day_type == "평일":
        trains = _TIME_CACHE["after"]["trains"]
    else:
        trains = _TIME_CACHE["before"]["trains"]

    return [t for t in trains if t["day_type"] == day_type]

def load_weather_hourly(date_str):
    """날씨 파일 로드 (없을 경우 기본 평년값 반환)"""
    wpath = WEATHER_DIR / f"{date_str}.json"
    if not wpath.exists():
        return None
    try:
        with open(wpath, encoding="utf-8") as f:
            return json.load(f).get("hourly", {})
    except Exception:
        return None

# ==========================================
# 3. 1일치 전체 열차 재차인원 추출
# ==========================================
def extract_single_day(date_str, model, output_dir, save_csv=False):
    day_type = get_day_type(date_str)
    is_weekend = 1 if day_type == "휴일" else 0
    plan_version = 1 if date_str >= PLAN_CHANGE_DATE else 0

    trains = load_subway_schedule(date_str, day_type)
    if not trains:
        print(f"⚠️ {date_str}: 해당 날짜의 운행 열차 정보가 없습니다.")
        return None

    weather = load_weather_hourly(date_str)
    weather_times = weather.get("time", []) if weather else []

    # 전체 열차 정차역에 대해 일괄 배치 예측(Batch Predict) 준비
    batch_rows = []
    meta_info = []

    for t_idx, t in enumerate(trains):
        train_id = t["train_id"]
        direction = t["direction"]
        dir_code = 0 if direction == "상행" else 1
        origin = t.get("origin", "")
        destination = t.get("destination", "")
        stops = t["stops"]
        n_stops = len(stops)

        for s_idx, st in enumerate(stops):
            s_name = st["station"]
            if s_name not in STATION_TO_IDX:
                continue
            station_id = STATION_TO_IDX[s_name]
            time_str = st["time"]
            hh = int(time_str.split(":")[0])
            norm_h = normalize_hour(hh)

            is_orig = (s_idx == 0)
            is_dest = (s_idx == n_stops - 1)

            # 날씨 매칭
            w_h = 0 if norm_h == 24 else norm_h
            w_key = f"{date_str}T{w_h:02d}:00"
            temp, precip, snow = 15.0, 0.0, 0.0
            if weather_times and w_key in weather_times:
                w_idx = weather_times.index(w_key)
                temp = float(weather.get("temperature_2m", [15.0])[w_idx])
                precip = float(weather.get("precipitation", [0.0])[w_idx])
                snow = float(weather.get("snowfall", [0.0])[w_idx])

            batch_rows.append({
                "station_idx": station_id,
                "hour": norm_h,
                "dir_code": dir_code,
                "is_weekend": is_weekend,
                "temp": temp,
                "precip": precip,
                "snow": snow,
                "plan_version": plan_version
            })

            meta_info.append({
                "train_index": t_idx,
                "train_id": train_id,
                "direction": direction,
                "origin": origin,
                "destination": destination,
                "station": s_name,
                "time": time_str,
                "hour": norm_h,
                "is_origin": is_orig,
                "is_destination": is_dest,
                "temp": temp,
                "precip": precip,
                "snow": snow
            })

    # 고속 일괄 추론
    X_df = pd.DataFrame(batch_rows)[[
        "station_idx", "hour", "dir_code", "is_weekend",
        "temp", "precip", "snow", "plan_version"
    ]]
    predicted_loads = np.clip(model.predict(X_df), 0, None)

    # 열차별 계층 구조로 재조립
    train_simulations = defaultdict(lambda: {
        "train_id": "",
        "day_type": day_type,
        "direction": "",
        "origin": "",
        "destination": "",
        "stops": []
    })

    flat_records = []

    for i, meta in enumerate(meta_info):
        t_id = meta["train_id"]
        load_val = round(float(predicted_loads[i]), 1)

        # 종점에서는 하차 완료로 잔류 재차가 0이 되므로 0 처리
        if meta["is_destination"]:
            load_val = 0.0

        congestion = get_congestion_level(load_val)

        sim = train_simulations[t_id]
        sim["train_id"] = t_id
        sim["direction"] = meta["direction"]
        sim["origin"] = meta["origin"]
        sim["destination"] = meta["destination"]
        sim["stops"].append({
            "station": meta["station"],
            "time": meta["time"],
            "hour": str(meta["hour"]),
            "load": load_val,
            "congestion": congestion,
            "is_origin": meta["is_origin"],
            "is_destination": meta["is_destination"],
            "temp": meta["temp"],
            "precip": meta["precip"]
        })

        if save_csv:
            flat_records.append({
                "date": date_str,
                "day_type": day_type,
                "train_id": t_id,
                "direction": meta["direction"],
                "station": meta["station"],
                "time": meta["time"],
                "hour": meta["hour"],
                "load": load_val,
                "congestion": congestion,
                "is_origin": meta["is_origin"],
                "is_destination": meta["is_destination"],
                "temp": meta["temp"],
                "precip": meta["precip"]
            })

    # JSON 저장
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"train_load_{date_str}.json"

    result_json = {
        "date": date_str,
        "day_type": day_type,
        "train_count": len(train_simulations),
        "total_stops": len(meta_info),
        "model_version": "HistGradientBoostingRegressor",
        "simulations": list(train_simulations.values())
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result_json, f, ensure_ascii=False, indent=2)

    # CSV 저장 (선택)
    if save_csv:
        csv_path = output_dir / f"train_load_{date_str}.csv"
        pd.DataFrame(flat_records).to_csv(csv_path, index=False, encoding="utf-8-sig")

    return json_path

# ==========================================
# 4. 메인 실행 함수
# ==========================================
def main():
    parser = argparse.ArgumentParser(description="열차별 재차인원 궤적 일괄 추출기")
    parser.add_argument("--date", type=str, default=None, help="추출할 단일 날짜 (YYYY-MM-DD)")
    parser.add_argument("--start-date", type=str, default=None, help="추출 시작 날짜 (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, default=None, help="추출 종료 날짜 (YYYY-MM-DD)")
    parser.add_argument("--model", type=str, default=str(DEFAULT_MODEL_PATH), help="학습된 모델 경로")
    parser.add_argument("--output-dir", type=str, default=str(DEFAULT_OUTPUT_DIR), help="결과 저장 폴더")
    parser.add_argument("--save-csv", action="store_true", help="JSON 외에 CSV 파일도 함께 생성")
    args = parser.parse_args()

    model_path = Path(args.model)
    if not model_path.exists():
        print(f"❌ 오류: 모델 파일이 없습니다: {model_path}")
        print("먼저 `python train_predict_model.py`를 실행하여 모델을 생성하세요.")
        return

    output_dir = Path(args.output_dir)
    print(f"모델 로드 중: {model_path} ...")
    model = joblib.load(model_path)
    print("✅ 모델 로드 완료.")

    # 날짜 목록 결정
    target_dates = []
    if args.date:
        target_dates = [args.date]
    elif args.start_date and args.end_date:
        cur = datetime.strptime(args.start_date, "%Y-%m-%d")
        end = datetime.strptime(args.end_date, "%Y-%m-%d")
        while cur <= end:
            target_dates.append(cur.strftime("%Y-%m-%d"))
            cur += timedelta(days=1)
    else:
        # 인자가 없으면 오늘 날짜 기본 수행
        today_str = datetime.now().strftime("%Y-%m-%d")
        print(f"ℹ️ 날짜 인자가 없어 오늘 날짜({today_str})를 기본으로 추출합니다.")
        target_dates = [today_str]

    print(f"\n=======================================================")
    print(f" 🚇 대전 1호선 열차별 재차인원 일괄 추출")
    print(f" 대상 날짜: 총 {len(target_dates)}일 ({target_dates[0]} ~ {target_dates[-1]})")
    print(f" 저장 위치: {output_dir}")
    print(f"=======================================================")

    t0 = time.time()
    success_count = 0

    for idx, d_str in enumerate(target_dates):
        out_file = extract_single_day(d_str, model, output_dir, save_csv=args.save_csv)
        if out_file:
            success_count += 1
            if len(target_dates) <= 5 or (idx + 1) % 10 == 0 or idx == len(target_dates) - 1:
                print(f"  [{idx+1}/{len(target_dates)}] {d_str} 추출 완료 -> {out_file.name}")

    elapsed = time.time() - t0
    print(f"\n🎉 전체 작업 완료! 총 {success_count}일간의 열차 재차인원 데이터가 저장되었습니다. (소요: {elapsed:.2f}초)")

if __name__ == "__main__":
    main()
