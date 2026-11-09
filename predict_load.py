"""
predict_load.py
미래 시점의 조건(날짜, 역, 시간대, 상/하행 방향, 날씨 등)을 입력받아,
학습된 모델을 통해 해당 열차의 예상 재차인원(Load) 및 혼잡도를 실시간으로 추론합니다.

사용법 (CLI):
  python predict_load.py --station 시청 --hour 18 --direction 하행 --temp 12.0
  python predict_load.py --station 대전 --hour 8 --direction 상행 --date 2026-11-15 --precip 5.0
"""

import sys
import argparse
from datetime import datetime
from pathlib import Path

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

import numpy as np
import pandas as pd
import joblib

MODEL_PATH = Path("./outputs/load_predictor.joblib")

STATION_NAMES = [
    "판암","신흥","대동","대전","중앙로","중구청","서대전네거리","오룡",
    "용문","탄방","시청","정부청사","갈마","월평","갑천","유성온천",
    "구암","현충원","월드컵경기장","노은","지족","반석"
]
STATION_TO_IDX = {name: i for i, name in enumerate(STATION_NAMES)}

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

def get_congestion_level(load):
    """대전 1호선 4량 1편성 기준 혼잡도 등급 (좌석 약 174석, 정원 450명)"""
    if load < 80:
        return "여유 (좌석 여유)"
    elif load < 180:
        return "보통 (착석 가능 또는 일부 입석)"
    elif load < 300:
        return "약간 혼잡 (입석 다수)"
    elif load < 450:
        return "혼잡 (손잡이 유지)"
    else:
        return "매우 혼잡 (출퇴근 피크 만원)"

def predict_train_load(
    station: str,
    hour: int,
    direction: str,
    date_str: str = None,
    temp: float = 15.0,
    precip: float = 0.0,
    snow: float = 0.0,
    model_path: Path = MODEL_PATH
):
    if not model_path.exists():
        raise FileNotFoundError(f"모델 파일이 없습니다: {model_path}\n먼저 train_predict_model.py를 실행하세요.")

    model = joblib.load(model_path)

    if station not in STATION_TO_IDX:
        raise ValueError(f"유효하지 않은 역명입니다: {station}\n가능한 역: {', '.join(STATION_NAMES)}")

    station_idx = STATION_TO_IDX[station]

    if direction not in ("상행", "하행"):
        raise ValueError(f"방향은 '상행' 또는 '하행'이어야 합니다: {direction}")
    dir_code = 0 if direction == "상행" else 1

    # 날짜로부터 요일 및 시각표 버전 판정
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    dt = datetime.strptime(date_str, "%Y-%m-%d")
    is_weekend = 1 if (dt.weekday() >= 5 or date_str in HOLIDAYS) else 0
    plan_version = 1 if date_str >= "2026-03-30" else 0

    # 피처 벡터 생성
    feature_cols = [
        "station_idx", "hour", "dir_code", "is_weekend",
        "temp", "precip", "snow", "plan_version"
    ]
    x_input = pd.DataFrame([{
        "station_idx": station_idx,
        "hour": hour,
        "dir_code": dir_code,
        "is_weekend": is_weekend,
        "temp": temp,
        "precip": precip,
        "snow": snow,
        "plan_version": plan_version
    }])[feature_cols]

    predicted_load = max(0.0, float(model.predict(x_input)[0]))
    congestion = get_congestion_level(predicted_load)

    return {
        "date": date_str,
        "day_type": "휴일" if is_weekend else "평일",
        "station": station,
        "hour": f"{hour:02d}:00",
        "direction": direction,
        "predicted_load": round(predicted_load, 1),
        "congestion": congestion,
        "weather": {
            "temp": f"{temp}°C",
            "precip": f"{precip}mm",
            "snow": f"{snow}cm"
        }
    }

def main():
    parser = argparse.ArgumentParser(description="열차 재차인원 실시간 추론기")
    parser.add_argument("--station", type=str, default="시청", help="역 이름 (예: 시청, 대전, 판암, 반석 등)")
    parser.add_argument("--hour", type=int, default=18, help="시간대 (5 ~ 24)")
    parser.add_argument("--direction", type=str, default="하행", choices=["상행", "하행"], help="운행 방향")
    parser.add_argument("--date", type=str, default=None, help="날짜 (YYYY-MM-DD, 기본값 오늘)")
    parser.add_argument("--temp", type=float, default=12.0, help="기온 (°C)")
    parser.add_argument("--precip", type=float, default=0.0, help="강수량 (mm)")
    parser.add_argument("--snow", type=float, default=0.0, help="적설량 (cm)")
    args = parser.parse_args()

    result = predict_train_load(
        station=args.station,
        hour=args.hour,
        direction=args.direction,
        date_str=args.date,
        temp=args.temp,
        precip=args.precip,
        snow=args.snow
    )

    print("\n" + "=" * 55)
    print(" 🚇 대전 1호선 열차 재차인원 및 혼잡도 예측 결과")
    print("=" * 55)
    print(f" * 기준 일자: {result['date']} ({result['day_type']})")
    print(f" * 정차 역:   {result['station']}역")
    print(f" * 운행 시각: {result['hour']}")
    print(f" * 운행 방향: {result['direction']}")
    print(f" * 날씨 조건: 기온 {result['weather']['temp']} / 강수 {result['weather']['precip']} / 적설 {result['weather']['snow']}")
    print("-" * 55)
    print(f" ▶ 예상 열차 재차인원: {result['predicted_load']} 명")
    print(f" ▶ 혼잡도 수준:        {result['congestion']}")
    print("=" * 55 + "\n")

if __name__ == "__main__":
    main()
