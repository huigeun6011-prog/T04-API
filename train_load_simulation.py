import json
from collections import defaultdict

# ==========================================
# 1. 경로
# ==========================================
REBOARDING_PATH = "reboarding_estimate_2025-11-04.json"
SUBWAY_TIME_PATH = "subway_time.json"
OUTPUT_PATH = "train_load_2025-11-04.json"

# ==========================================
# 2. 입력 로드
# ==========================================
with open(REBOARDING_PATH, encoding="utf-8") as f:
    reboarding = json.load(f)

with open(SUBWAY_TIME_PATH, encoding="utf-8") as f:
    subway_time = json.load(f)

# 해당 날짜의 요일 구분 (reboarding 파일에 day_type 있음)
target_day_type = reboarding["day_type"]   # 예: "평일"

boarding_per_train  = reboarding["boarding_per_train"]   # {역: {시간: 값}}
alighting_per_train = reboarding["alighting_per_train"]  # {역: {시간: 값}}

# ==========================================
# 3. 오류 수집기
# ==========================================
errors = []   # (카테고리, 열차ID, 역, 시각, 시간대, 상세)

def report_error(category, train_id, station, time_str, hour_key, detail):
    errors.append({
        "category": category,
        "train_id": train_id,
        "station": station,
        "time": time_str,
        "hour": hour_key,
        "detail": detail,
    })

# ==========================================
# 4. 정차 시각 → 시간대 키
# ==========================================
def time_to_hour_key(time_str):
    """
    '05:30' -> '5'
    '24:12' -> '24'
    '04:59' -> '4'  (있을 수 없지만, 발생 시 오류로 잡기 위해 그대로 반환)
    """
    hh_str, mm_str = time_str.split(":")
    hh = int(hh_str)
    return str(hh)   # 24 이상도 그대로 "24", "25" 등

# ==========================================
# 5. per-train 값 조회 (오류 보고 포함)
# ==========================================
def get_board(train_id, station, time_str, hour_key):
    """승차 per-train 값 조회. 결측/비정상 시 오류 보고 후 0."""
    # 5시 미만 정차는 있을 수 없음
    hh = int(hour_key)
    if hh < 5:
        report_error("정차시각_5시미만", train_id, station, time_str, hour_key,
                     f"5시 미만 정차 시각({time_str})은 존재할 수 없음")
        return 0.0

    station_map = boarding_per_train.get(station, {})
    if hour_key not in station_map:
        report_error("승차_키부재", train_id, station, time_str, hour_key,
                     f"boarding_per_train[{station}]에 '{hour_key}' 키 없음")
        return 0.0
    val = station_map[hour_key]
    if val is None:
        report_error("승차_값null", train_id, station, time_str, hour_key,
                     f"boarding_per_train[{station}]['{hour_key}'] 값이 null")
        return 0.0
    return float(val)

def get_alight(train_id, station, time_str, hour_key):
    """하차 per-train 값 조회. 결측/비정상 시 오류 보고 후 0."""
    hh = int(hour_key)
    if hh < 5:
        report_error("정차시각_5시미만", train_id, station, time_str, hour_key,
                     f"5시 미만 정차 시각({time_str})은 존재할 수 없음")
        return 0.0

    station_map = alighting_per_train.get(station, {})
    if hour_key not in station_map:
        report_error("하차_키부재", train_id, station, time_str, hour_key,
                     f"alighting_per_train[{station}]에 '{hour_key}' 키 없음")
        return 0.0
    val = station_map[hour_key]
    if val is None:
        report_error("하차_값null", train_id, station, time_str, hour_key,
                     f"alighting_per_train[{station}]['{hour_key}'] 값이 null")
        return 0.0
    return float(val)

# ==========================================
# 6. 열차별 시뮬레이션
# ==========================================
def simulate_train(train):
    train_id   = train["train_id"]
    day_type   = train["day_type"]
    direction  = train["direction"]
    origin     = train["origin"]
    destination= train["destination"]
    stops      = train["stops"]

    # 요일 구분이 다르면 이 열차는 대상 아님 (해당 날짜만)
    if day_type != target_day_type:
        return None

    load = 0.0
    stop_records = []

    for idx, stop in enumerate(stops):
        station = stop["station"]
        time_str = stop["time"]
        hour_key = time_to_hour_key(time_str)

        is_origin      = (idx == 0)                  # 첫 정차역 = 출발역
        is_destination = (idx == len(stops) - 1)     # 마지막 정차역 = 종점

        # 방어: origin/destination 필드와 실제 첫/마지막 정차역이 다르면 오류
        if is_origin and station != origin:
            report_error("출발역_불일치", train_id, station, time_str, hour_key,
                         f"첫 정차역({station}) != origin({origin})")
        if is_destination and station != destination:
            report_error("종점_불일치", train_id, station, time_str, hour_key,
                         f"마지막 정차역({station}) != destination({destination})")

        if is_origin:
            board  = get_board(train_id, station, time_str, hour_key)
            alight = 0.0   # 조회 생략
        elif is_destination:
            board  = 0.0   # 조회 생략
            alight = get_alight(train_id, station, time_str, hour_key)
        else:
            board  = get_board(train_id, station, time_str, hour_key)
            alight = get_alight(train_id, station, time_str, hour_key)

        # 하차 → 승차 순서로 누적
        load -= alight
        load += board

        stop_records.append({
            "station": station,
            "time": time_str,
            "hour": hour_key,
            "board": board,
            "alight": alight,
            "load_after": load,
            "is_origin": is_origin,
            "is_destination": is_destination,
        })

    return {
        "train_id": train_id,
        "day_type": day_type,
        "direction": direction,
        "origin": origin,
        "destination": destination,
        "stops": stop_records,
        "final_load": load,
    }

# ==========================================
# 7. 전체 실행
# ==========================================
simulations = []
for train in subway_time["trains"]:
    sim = simulate_train(train)
    if sim is not None:
        simulations.append(sim)

# ==========================================
# 8. 저장
# ==========================================
output = {
    "date": reboarding["date"],
    "day_type": target_day_type,
    "train_count": len(simulations),
    "simulations": simulations,
    "errors": errors,
}
with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)
print(f"저장 완료: {OUTPUT_PATH}")

# ==========================================
# 9. 리포트
# ==========================================
print("\n" + "=" * 70)
print(f"[요약] 날짜: {reboarding['date']} / 요일: {target_day_type} / 열차 수: {len(simulations)}")
print("=" * 70)

# 9-1. 종점 잔류 인원 전체 출력
print("\n[열차별 종점 잔류 인원]")
print(f"{'열차ID':<20} {'방향':<6} {'출발':<12} {'종점':<12} {'종점재차':>12}")
print("-" * 70)
for sim in simulations:
    print(f"{sim['train_id']:<20} {sim['direction']:<6} "
          f"{sim['origin']:<12} {sim['destination']:<12} "
          f"{sim['final_load']:>12.4f}")

# 9-2. 오류 요약
print("\n" + "=" * 70)
print(f"[오류 보고] 총 {len(errors)}건")
print("=" * 70)
if not errors:
    print("없음 ✅")
else:
    # 카테고리별 집계
    cat_count = defaultdict(int)
    for e in errors:
        cat_count[e["category"]] += 1
    print("[카테고리별 건수]")
    for cat, cnt in sorted(cat_count.items(), key=lambda x: -x[1]):
        print(f"  {cat:<20} {cnt:>6}건")

    print("\n[상세 (최대 100건)]")
    for e in errors[:100]:
        print(f"  [{e['category']}] {e['train_id']} / {e['station']} "
              f"@ {e['time']} (hour={e['hour']}) — {e['detail']}")
    if len(errors) > 100:
        print(f"  ... 외 {len(errors) - 100}건 (전체는 JSON의 errors 참조)")

# 9-3. 종점 재차 분포 요약
print("\n" + "=" * 70)
print("[종점 재차 분포 요약]")
print("=" * 70)
if simulations:
    finals = [s["final_load"] for s in simulations]
    n = len(finals)
    mean = sum(finals) / n
    abs_mean = sum(abs(x) for x in finals) / n
    max_abs = max(abs(x) for x in finals)
    nonzero = sum(1 for x in finals if abs(x) > 1e-9)
    print(f"  열차 수:        {n}")
    print(f"  평균:           {mean:+.6f}")
    print(f"  절대값 평균:    {abs_mean:.6f}")
    print(f"  최대 절대값:    {max_abs:.6f}")
    print(f"  0이 아닌 열차:  {nonzero} / {n}")

    # 방향별
    print("\n[방향별]")
    for direction in ("상행", "하행"):
        vals = [s["final_load"] for s in simulations if s["direction"] == direction]
        if vals:
            m = sum(vals) / len(vals)
            am = sum(abs(x) for x in vals) / len(vals)
            print(f"  {direction}: n={len(vals)}, 평균={m:+.6f}, 절대평균={am:.6f}")