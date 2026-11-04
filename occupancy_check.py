import json
import os
from datetime import datetime, timedelta
from collections import defaultdict

# ==========================================
# 1. 경로 및 상수
# ==========================================
STATION_HOURLY_PATH = "station_hourly.json"
SUBWAY_DATA_DIR     = "./data/processed/subway"
TARGET_DATE         = "2025-11-04"

STATION_ID_TO_NAME = {
    101: "판암", 102: "신흥", 103: "대동", 104: "대전",
    105: "중앙로", 106: "중구청", 107: "서대전네거리", 108: "오룡",
    109: "용문", 110: "탄방", 111: "시청", 112: "정부청사",
    113: "갈마", 114: "월평", 115: "갑천", 116: "유성온천",
    117: "구암", 118: "현충원", 119: "월드컵경기장", 120: "노은",
    121: "지족", 122: "반석",
}

# ==========================================
# 2. 요일 판정
# ==========================================
HOLIDAYS = {
    "2025-01-01",
    "2025-01-27", "2025-01-28", "2025-01-29", "2025-01-30",
    "2025-03-01", "2025-03-03",
    "2025-05-05", "2025-05-06",
    "2025-06-03", "2025-06-06",
    "2025-08-15",
    "2025-10-03", "2025-10-05", "2025-10-06", "2025-10-07",
    "2025-10-08", "2025-10-09",
    "2025-12-25",
    "2026-01-01",
    "2026-02-16", "2026-02-17", "2026-02-18",
    "2026-03-01", "2026-03-02",
    "2026-05-05", "2026-05-24", "2026-05-25",
    "2026-06-06",
    "2026-08-15", "2026-08-17",
    "2026-09-24", "2026-09-25", "2026-09-26",
    "2026-10-03", "2026-10-05", "2026-10-09",
    "2026-12-25",
}

def get_day_type(date_str):
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

# 24시(다음날 0시) 데이터 = 11-04 막차의 지연 하차
next_date = (datetime.strptime(TARGET_DATE, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
next_path = os.path.join(SUBWAY_DATA_DIR, f"{next_date}.json")
if not os.path.exists(next_path):
    raise FileNotFoundError(
        f"{next_date}.json 이 없습니다. "
        f"{TARGET_DATE} 영업일의 24시(막차 지연 하차) 데이터를 처리하려면 다음날 파일이 필요합니다."
    )
with open(next_path, encoding="utf-8") as f:
    next_subway_data = json.load(f)

day_type = get_day_type(TARGET_DATE)
print(f"날짜: {TARGET_DATE}, 요일 구분: {day_type}")

if day_type not in station_hourly:
    raise KeyError(f"station_hourly.json에 '{day_type}' 키가 없습니다.")

hourly_for_day = station_hourly[day_type]

# ==========================================
# 4. 분모 계산
# ==========================================
boardings_denom  = {}
alightings_denom = {}

for station, hours in hourly_for_day.items():
    boardings_denom[station]  = {}
    alightings_denom[station] = {}
    for h, cell in hours.items():
        boardings_denom[station][h]  = cell["departures"] + cell["passes"]
        alightings_denom[station][h] = cell["passes"] + cell["arrivals"]

# ==========================================
# 4-1. 24시 귀속 대상 시간대 판정 (24시 우선, 23시 폴백)
# ==========================================
def get_last_train_hour(station):
    hours = hourly_for_day.get(station, {})
    numeric_hours = []
    for h in hours.keys():
        try:
            numeric_hours.append(int(h))
        except (ValueError, TypeError):
            continue
    return max(numeric_hours) if numeric_hours else None

def get_alighting_target_hour(station, prefer=24, fallback=23):
    """0시 하차(막차 지연 하차)를 귀속시킬 시간대."""
    for h in (str(prefer), str(fallback)):
        denom = alightings_denom.get(station, {}).get(h, 0)
        if denom > 0:
            return h
    return None

def is_boarding_possible_at_zero(station):
    """다음날 0시대 승차가 가능한지 (당일 마지막 열차 출발 이후인지)."""
    hours = hourly_for_day.get(station, {})
    h24 = hours.get("24", {})
    if h24.get("departures", 0) > 0:
        return True
    h23 = hours.get("23", {})
    if h23.get("departures", 0) > 0:
        return False
    last = get_last_train_hour(station)
    if last is None:
        return False
    return hours.get(str(last), {}).get("departures", 0) > 0

# ==========================================
# 5. 승차/하차 배정
# ==========================================
boarding_estimate  = {}
alighting_estimate = {}

total_boarding_original  = 0
total_boarding_assigned  = 0.0
total_alighting_original = 0
total_alighting_assigned = 0.0

boarding_errors  = defaultdict(dict)
alighting_errors = defaultdict(dict)

zero_hour_adjustments = []

def assign_alighting(station, hour_key, count):
    global total_alighting_original, total_alighting_assigned
    denom = alightings_denom.get(station, {}).get(hour_key, 0)
    total_alighting_original += count
    if denom == 0:
        alighting_estimate[station][hour_key] = None
        alighting_errors[station][hour_key] = count
        return False
    per_train = count / denom
    if alighting_estimate[station].get(hour_key) is None or hour_key not in alighting_estimate[station]:
        alighting_estimate[station][hour_key] = per_train
    else:
        alighting_estimate[station][hour_key] += per_train
    total_alighting_assigned += per_train * denom
    alighting_errors[station][hour_key] = 0.0
    return True

def assign_boarding(station, hour_key, count):
    global total_boarding_original, total_boarding_assigned
    denom = boardings_denom.get(station, {}).get(hour_key, 0)
    total_boarding_original += count
    if denom == 0:
        boarding_estimate[station][hour_key] = None
        boarding_errors[station][hour_key] = count
        return False
    per_train = count / denom
    if boarding_estimate[station].get(hour_key) is None or hour_key not in boarding_estimate[station]:
        boarding_estimate[station][hour_key] = per_train
    else:
        boarding_estimate[station][hour_key] += per_train
    total_boarding_assigned += per_train * denom
    boarding_errors[station][hour_key] = 0.0
    return True

for sid_str, station_data in subway_data.get("stations", {}).items():
    sid = int(sid_str)
    station = STATION_ID_TO_NAME.get(sid)
    if station is None:
        print(f"⚠️ 알 수 없는 역 ID: {sid}")
        continue

    boardings  = station_data.get("boardings",  {})
    alightings = station_data.get("alightings", {})

    boarding_estimate[station]  = {}
    alighting_estimate[station] = {}

    # --------------------------------------------------
    # 5-1. 당일 파일의 1~23시 승차/하차
    #   (당일 파일의 "0" 키는 11-03 영업일 소관이므로 사용하지 않음)
    # --------------------------------------------------
    for hour_str, boarding_count in boardings.items():
        if int(hour_str) == 0:
            continue   # 당일 0시 = 전날 영업일 막차 → 제외
        hour_key = str(int(hour_str))
        assign_boarding(station, hour_key, boarding_count)

    for hour_str, alighting_count in alightings.items():
        if int(hour_str) == 0:
            continue   # 당일 0시 = 전날 영업일 막차 → 제외
        hour_key = str(int(hour_str))
        assign_alighting(station, hour_key, alighting_count)

    # --------------------------------------------------
    # 5-2. 다음날 0시 → 당일 24시(또는 23시) 귀속
    #   = 당일 막차가 자정을 넘겨 하차한 기록
    # --------------------------------------------------
    next_station_data = next_subway_data.get("stations", {}).get(sid_str, {})

    # --- 다음날 0시 승차: 마지막 열차 출발 이후면 불가 → 하차에서 차감/폐기 ---
    boarding_count_next0 = next_station_data.get("boardings", {}).get("0")
    if boarding_count_next0 is not None and boarding_count_next0 > 0:
        if not is_boarding_possible_at_zero(station):
            alighting_count_next0 = next_station_data.get("alightings", {}).get("0")
            if alighting_count_next0 is not None and alighting_count_next0 > 0:
                # 같은 다음날 0시 하차에서 1 차감
                next_station_data["alightings"]["0"] = alighting_count_next0 - 1
                zero_hour_adjustments.append(
                    ("승차(다음날0시)", station, "24", boarding_count_next0,
                     "하차에서 1 차감", "마지막 열차 출발 이후 승차 불가")
                )
            else:
                zero_hour_adjustments.append(
                    ("승차(다음날0시)", station, "24", boarding_count_next0,
                     "폐기", "마지막 열차 출발 이후 + 하차 기록 없음")
                )
        else:
            assign_boarding(station, "24", boarding_count_next0)

    # --- 다음날 0시 하차: 24시 우선, 23시 폴백 ---
    alighting_count_next0 = next_station_data.get("alightings", {}).get("0")
    if alighting_count_next0 is not None and alighting_count_next0 > 0:
        target_hour = get_alighting_target_hour(station, prefer=24, fallback=23)
        if target_hour is None:
            alighting_estimate[station]["24"] = None
            alighting_errors[station]["24"] = alighting_count_next0
            zero_hour_adjustments.append(
                ("하차(다음날0시)", station, "24", alighting_count_next0,
                 "배정 불가", "24시·23시 하차 분모 모두 0")
            )
        else:
            assign_alighting(station, target_hour, alighting_count_next0)
            reason = "당일 막차 지연 하차"
            if target_hour != "24":
                reason += f" (24시 열차 없음 → {target_hour}시 폴백)"
            zero_hour_adjustments.append(
                ("하차(다음날0시)", station, "24", alighting_count_next0,
                 f"{target_hour}시로 귀속", reason)
            )

# ==========================================
# 6. 저장
# ==========================================
output = {
    "date": TARGET_DATE,
    "day_type": day_type,
    "boarding_per_train":  boarding_estimate,
    "alighting_per_train": alighting_estimate,
}

out_path = f"reboarding_estimate_{TARGET_DATE}.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)
print(f"\n저장 완료: {out_path}")

# ==========================================
# 7. 오차 검증
# ==========================================
print("\n" + "=" * 60)
print("[오차 검증]")
print("=" * 60)

boarding_diff  = total_boarding_assigned  - total_boarding_original
alighting_diff = total_alighting_assigned - total_alighting_original

print(f"승차 원본 총합: {total_boarding_original:,}")
print(f"승차 배정 총합: {total_boarding_assigned:,.4f}")
print(f"승차 오차:      {boarding_diff:+.6f}")
print()
print(f"하차 원본 총합: {total_alighting_original:,}")
print(f"하차 배정 총합: {total_alighting_assigned:,.4f}")
print(f"하차 오차:      {alighting_diff:+.6f}")

# ==========================================
# 8. 0시(다음날 0시 → 24시) 처리 내역
# ==========================================
print("\n" + "=" * 60)
print("[0시(다음날 0시 → 24시) 처리 내역]")
print("=" * 60)
if not zero_hour_adjustments:
    print("없음")
else:
    print(f"{'구분':<18} {'역명':<16} {'귀속':<4} {'원본':>6} {'처리':<16} 사유")
    print("-" * 95)
    for kind, st, h, val, action, reason in zero_hour_adjustments:
        print(f"{kind:<18} {st:<16} {h:<4} {val:>6} {action:<16} {reason}")

# ==========================================
# 9. 분모 0 케이스
# ==========================================
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
# 10. 역별 배정 총합 검증 (상위 5개)
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