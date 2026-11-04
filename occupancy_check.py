import json
import os
from datetime import datetime
from collections import defaultdict

# ==========================================
# 1. 경로 및 상수
# ==========================================
STATION_HOURLY_PATH = "station_hourly.json"
SUBWAY_DATA_DIR     = "./data/processed/subway"
TARGET_DATE         = "2025-11-01"   # 테스트할 날짜

# 역 ID ↔ 역명 매핑 (101 판암 ~ 122 반석)
STATION_ID_TO_NAME = {
    101: "판암", 102: "신흥", 103: "대동", 104: "대전",
    105: "중앙로", 106: "중구청", 107: "서대전네거리", 108: "오룡",
    109: "용문", 110: "탄방", 111: "시청", 112: "정부청사",
    113: "갈마", 114: "월평", 115: "갑천", 116: "유성온천",
    117: "구암", 118: "현충원", 119: "월드컵경기장", 120: "노은",
    121: "지족", 122: "반석",
}

# ==========================================
# 2. 요일 판정 (토·일 = 휴일, 나머지 = 평일)
# ==========================================
from datetime import datetime

# ==========================================
# 법정 공휴일 집합 (2025, 2026)
# ==========================================
HOLIDAYS = {
    # --- 2025년 ---
    "2025-01-01",  # 신정
    "2025-01-27", "2025-01-28", "2025-01-29", "2025-01-30",  # 설날 연휴
    "2025-03-01",  # 삼일절 (토요일)
    "2025-03-03",  # 삼일절 대체공휴일
    "2025-05-05",  # 어린이날 + 부처님오신날
    "2025-05-06",  # 어린이날 대체공휴일
    "2025-06-03",  # 대통령선거일 (임시공휴일)
    "2025-06-06",  # 현충일
    "2025-08-15",  # 광복절
    "2025-10-03",  # 개천절
    "2025-10-05", "2025-10-06", "2025-10-07",  # 추석 연휴
    "2025-10-08",  # 추석 대체공휴일
    "2025-10-09",  # 한글날
    "2025-12-25",  # 성탄절

    # --- 2026년 ---
    "2026-01-01",  # 신정
    "2026-02-16", "2026-02-17", "2026-02-18",  # 설날 연휴
    "2026-03-01",  # 삼일절 (일요일)
    "2026-03-02",  # 삼일절 대체공휴일
    "2026-05-05",  # 어린이날
    "2026-05-24",  # 부처님오신날 (일요일)
    "2026-05-25",  # 부처님오신날 대체공휴일
    "2026-06-06",  # 현충일 (토요일)
    "2026-08-15",  # 광복절 (토요일)
    "2026-08-17",  # 광복절 대체공휴일
    "2026-09-24", "2026-09-25", "2026-09-26",  # 추석 연휴
    "2026-10-03",  # 개천절 (토요일)
    "2026-10-05",  # 개천절 대체공휴일
    "2026-10-09",  # 한글날
    "2026-12-25",  # 성탄절
}

def get_day_type(date_str):
    """
    날짜 문자열(YYYY-MM-DD)을 받아 '평일' 또는 '휴일'을 반환.
    - 공휴일이면 무조건 '휴일'
    - 그 외에는 토/일이면 '휴일', 평일이면 '평일'
    """
    if date_str in HOLIDAYS:
        return "휴일"
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return "휴일" if dt.weekday() >= 5 else "평일"

# ==========================================
# 3. 데이터 로드
# ==========================================
with open(STATION_HOURLY_PATH, encoding="utf-8") as f:
    station_hourly = json.load(f)

date_path = os.path.join(SUBWAY_DATA_DIR, f"{TARGET_DATE}.json")
with open(date_path, encoding="utf-8") as f:
    subway_data = json.load(f)

day_type = get_day_type(TARGET_DATE)
print(f"날짜: {TARGET_DATE}, 요일 구분: {day_type}")

if day_type not in station_hourly:
    raise KeyError(f"station_hourly.json에 '{day_type}' 키가 없습니다.")

hourly_for_day = station_hourly[day_type]  # {역명: {시간대: {departures, passes, arrivals}}}

# ==========================================
# 4. 역별·시간대별 분모 계산
# ==========================================
# boardings_denom[역][시간] = departures + passes
# alightings_denom[역][시간] = passes + arrivals
boardings_denom  = {}
alightings_denom = {}

for station, hours in hourly_for_day.items():
    boardings_denom[station]  = {}
    alightings_denom[station] = {}
    for h, cell in hours.items():
        boardings_denom[station][h]  = cell["departures"] + cell["passes"]
        alightings_denom[station][h] = cell["passes"] + cell["arrivals"]

# ==========================================
# 5. 승차 인원 배정
#   원본 승차 인원 / 승차 분모 = 열차 1대당 승차 인원
# ==========================================
boarding_estimate = {}   # {역: {시간: 열차당승차}}
alighting_estimate = {}

total_boarding_original = 0
total_boarding_assigned = 0.0
total_alighting_original = 0
total_alighting_assigned = 0.0

# 오차 상세 기록
boarding_errors  = defaultdict(dict)   # {역: {시간: 오차}}
alighting_errors = defaultdict(dict)

for sid_str, station_data in subway_data.get("stations", {}).items():
    sid = int(sid_str)
    station = STATION_ID_TO_NAME.get(sid)
    if station is None:
        print(f"⚠️ 알 수 없는 역 ID: {sid}")
        continue

    boardings  = station_data.get("boardings",  {})
    alightings = station_data.get("alightings", {})

    # --- 승차 ---
    boarding_estimate[station] = {}
    for hour_str, boarding_count in boardings.items():
        hour_key = str(int(hour_str))   # "05" → "5"
        denom = boardings_denom.get(station, {}).get(hour_key, 0)

        total_boarding_original += boarding_count
        if denom == 0:
            # 분모 0인데 인원이 있으면 배정 불가
            boarding_estimate[station][hour_key] = None
            boarding_errors[station][hour_key] = boarding_count
            continue

        per_train = boarding_count / denom
        boarding_estimate[station][hour_key] = per_train
        total_boarding_assigned += per_train * denom
        boarding_errors[station][hour_key] = 0.0

    # --- 하차 ---
    alighting_estimate[station] = {}
    for hour_str, alighting_count in alightings.items():
        hour_key = str(int(hour_str))
        denom = alightings_denom.get(station, {}).get(hour_key, 0)

        total_alighting_original += alighting_count
        if denom == 0:
            alighting_estimate[station][hour_key] = None
            alighting_errors[station][hour_key] = alighting_count
            continue

        per_train = alighting_count / denom
        alighting_estimate[station][hour_key] = per_train
        total_alighting_assigned += per_train * denom
        alighting_errors[station][hour_key] = 0.0

# ==========================================
# 6. 저장 (JSON)
# ==========================================
output = {
    "date": TARGET_DATE,
    "day_type": day_type,
    "boarding_per_train":  boarding_estimate,   # {역: {시간: 열차당 승차}}
    "alighting_per_train": alighting_estimate,   # {역: {시간: 열차당 하차}}
}

out_path = f"reboarding_estimate_{TARGET_DATE}.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)
print(f"저장 완료: {out_path}")

# ==========================================
# 7. 오차 검증
# ==========================================
print("\n" + "=" * 60)
print("[오차 검증]")
print("=" * 60)

# 배정된 인원 = per_train × denom
# 총 배정 인원과 원본 총 인원의 차이
boarding_diff  = total_boarding_assigned  - total_boarding_original
alighting_diff = total_alighting_assigned - total_alighting_original

print(f"승차 원본 총합: {total_boarding_original:,}")
print(f"승차 배정 총합: {total_boarding_assigned:,.4f}")
print(f"승차 오차:      {boarding_diff:+.6f}")
print()
print(f"하차 원본 총합: {total_alighting_original:,}")
print(f"하차 배정 총합: {total_alighting_assigned:,.4f}")
print(f"하차 오차:      {alighting_diff:+.6f}")

# 분모 0 케이스 목록
print("\n" + "=" * 60)
print("[분모 0으로 배정 불가한 항목]")
print("=" * 60)
zero_cases = []
for station, hours in boarding_errors.items():
    for h, err in hours.items():
        if err != 0:
            zero_cases.append(("승차", station, h, err))
for station, hours in alighting_errors.items():
    for h, err in hours.items():
        if err != 0:
            zero_cases.append(("하차", station, h, err))

if not zero_cases:
    print("없음 ✅")
else:
    print(f"{'구분':<4} {'역명':<16} {'시간':<4} {'원본인원':>8}")
    print("-" * 40)
    for kind, st, h, err in zero_cases:
        print(f"{kind:<4} {st:<16} {h:<4} {err:>8}")

# ==========================================
# 8. 방향별 합계 검증 (참고용)
#   station_hourly.json에 방향 구분이 없으므로
#   역 전체 합으로만 검증
# ==========================================
print("\n" + "=" * 60)
print("[역별 배정 총합 검증] (상위 5개)")
print("=" * 60)
station_totals = []
for station in boarding_estimate:
    total_b = sum(
        v * boardings_denom[station].get(h, 0)
        for h, v in boarding_estimate[station].items() if v is not None
    )
    total_a = sum(
        v * alightings_denom[station].get(h, 0)
        for h, v in alighting_estimate[station].items() if v is not None
    )
    station_totals.append((station, total_b, total_a))

for st, b, a in sorted(station_totals, key=lambda x: -x[1])[:5]:
    print(f"  {st:<16} 승차 {b:>12,.1f} / 하차 {a:>12,.1f}")