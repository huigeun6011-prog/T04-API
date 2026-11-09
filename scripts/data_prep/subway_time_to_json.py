import pandas as pd
import json
from datetime import timedelta
from collections import Counter

# ==========================================
# 1. 파일 로드
# ==========================================
FILE_PATH = "../../data/raw/subway_time/대전교통공사_열차운행 상황 및 시각표_20250930.csv"

for enc in ['cp949', 'euc-kr', 'utf-8-sig']:
    try:
        df = pd.read_csv(FILE_PATH, encoding=enc)
        print(f"인코딩 '{enc}' 로드 성공")
        break
    except UnicodeDecodeError:
        continue
else:
    raise FileNotFoundError(f"파일 로드 실패: {FILE_PATH}")

# ==========================================
# 2. 역 순서 및 역간 소요시간
# ==========================================
stations = [
    "판암", "신흥", "대동", "대전", "중앙로", "중구청",
    "서대전네거리", "오룡", "용문", "탄방", "시청", "정부청사",
    "갈마", "월평", "갑천", "유성온천", "구암", "현충원",
    "월드컵경기장", "노은", "지족", "반석"
]

down_seq = stations
up_seq   = list(reversed(stations))

base_times = {
    "판암": 2, "신흥": 2, "대동": 2, "대전": 2, "중앙로": 1, "중구청": 2,
    "서대전네거리": 2, "오룡": 2, "용문": 3, "탄방": 1, "시청": 2, "정부청사": 2,
    "갈마": 2, "월평": 2, "갑천": 2, "유성온천": 2, "구암": 2, "현충원": 2,
    "월드컵경기장": 2, "노은": 2, "지족": 2, "반석": 0
}

MIN_GAP, MAX_GAP = 1, 4

# ==========================================
# 3. 유틸리티
# ==========================================
def parse_time(hour, minute_str):
    return timedelta(hours=int(hour), minutes=int(minute_str))

def fmt_td(td):
    total = int(td.total_seconds() // 60)
    h, m = divmod(total, 60)
    return f"{h:02d}:{m:02d}"

def get_departures(station_name, direction, day_type):
    """행선지 표시는 무시하고 시각만 반환."""
    subset = df[
        (df['역명'] == f"{station_name}역") &
        (df['운행방향'] == direction) &
        (df['휴일구분'] == day_type)
    ]
    result = []
    for _, row in subset.iterrows():
        hour = int(row['시간대'])
        minutes_str = str(row['동 시간대 분'])
        if pd.isna(minutes_str) or minutes_str == 'nan':
            continue
        for tok in minutes_str.split():
            base = tok.split('(')[0]
            if base.isdigit():
                result.append(parse_time(hour, base))
    return sorted(result)

# ==========================================
# 4. 열차 복원 (연결 그래프)
# ==========================================
def build_trains(seq, direction, day_type):
    per_station = {st: get_departures(st, direction, day_type) for st in seq}

    next_map = {}
    prev_map = {}

    for i in range(len(seq) - 1):
        cur_list = per_station[seq[i]]
        nxt_times_sorted = sorted(per_station[seq[i + 1]])

        for t in cur_list:
            lo = t + timedelta(minutes=MIN_GAP)
            hi = t + timedelta(minutes=MAX_GAP)
            candidates = [nt for nt in nxt_times_sorted if lo <= nt <= hi]
            if candidates:
                chosen = candidates[0]
                next_map[(i, t)] = (i + 1, chosen)
                prev_map[(i + 1, chosen)] = (i, t)

    all_nodes = set()
    for i, st in enumerate(seq):
        for t in per_station[st]:
            all_nodes.add((i, t))

    starts = [n for n in all_nodes if n not in prev_map]

    trains = []
    used = set()
    for start in sorted(starts, key=lambda x: (x[1], x[0])):
        path = [start]
        cur = start
        while cur in next_map:
            cur = next_map[cur]
            path.append(cur)
        if len(path) >= 2:
            for n in path:
                used.add(n)
            trains.append({
                "direction": direction,
                "day_type": day_type,
                "path": [(seq[i], t) for i, t in path],
            })

    for n in sorted(all_nodes - used, key=lambda x: (x[1], x[0])):
        trains.append({
            "direction": direction,
            "day_type": day_type,
            "path": [(seq[n[0]], n[1])],
        })

    return trains

# ==========================================
# 5. 전체 열차 생성
# ==========================================
all_trains = []
for day_type in ['평일', '휴일']:
    all_trains.extend(build_trains(down_seq, "하행", day_type))
    all_trains.extend(build_trains(up_seq,   "상행", day_type))

# ==========================================
# 6. ID 부여 + JSON 직렬화
# ==========================================
all_trains.sort(key=lambda tr: (tr["day_type"], tr["direction"], tr["path"][0][1]))

output = {"trains": []}
for idx, tr in enumerate(all_trains, start=1):
    first_st, first_t = tr["path"][0]
    last_st,  last_t  = tr["path"][-1]
    train_id = f"{tr['day_type']}-{tr['direction']}-{idx:03d}"

    stops = [{"station": st, "time": fmt_td(t)} for st, t in tr["path"]]
    output["trains"].append({
        "train_id": train_id,
        "day_type": tr["day_type"],
        "direction": tr["direction"],
        "origin": first_st,
        "origin_depart": fmt_td(first_t),
        "destination": last_st,
        "destination_arrive": fmt_td(last_t),
        "stop_count": len(stops),
        "interpolated": False,
        "stops": stops,
    })

# ==========================================
# 7. 종착역 보간 (모든 열차 예외 없음)
# ==========================================
# 매칭이 끝난 마지막 역 X에서, 다음 역 Y를 X시각 + base_times[X]로 추가.
# Y가 종착역이 된다.

interpolated_count = 0
for t in output['trains']:
    seq = up_seq if t['direction'] == '상행' else down_seq
    last_st = t['stops'][-1]['station']

    # 마지막 역의 인덱스
    if last_st not in seq:
        continue
    last_idx = seq.index(last_st)

    # 다음 역이 없으면 (이미 노선 끝) 보간 불필요
    if last_idx + 1 >= len(seq):
        continue

    next_st = seq[last_idx + 1]
    gap = base_times.get(last_st, 2)
    if gap <= 0:
        continue

    # 마지막 시각 + gap = 다음 역 도착 시각
    last_time_str = t['stops'][-1]['time']
    h, m = map(int, last_time_str.split(':'))
    total = h * 60 + m + gap
    next_time_str = f"{total//60:02d}:{total%60:02d}"

    t['stops'].append({"station": next_st, "time": next_time_str})
    t['destination'] = next_st
    t['destination_arrive'] = next_time_str
    t['stop_count'] = len(t['stops'])
    t['interpolated'] = True
    interpolated_count += 1

print(f"\n종착역 보간 적용: {interpolated_count}대")

# ==========================================
# 8. 저장
# ==========================================
with open("../../data/processed/subway_time/subway_time.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)
print("subway_time.json 저장 완료")

# ==========================================
# 9. 요약
# ==========================================
print(f"\n총 열차 수: {len(output['trains'])}")

dir_count = Counter((t["day_type"], t["direction"]) for t in output["trains"])
print("\n[방향별 열차 수]")
for k, v in sorted(dir_count.items()):
    print(f"  {k[0]} {k[1]}: {v}대")

full = [t for t in output['trains'] if t["stop_count"] == 22]
print(f"\n[풀주행(22역) 열차: {len(full)}대]")
full_by = Counter((t["day_type"], t["direction"]) for t in full)
for k, v in sorted(full_by.items()):
    print(f"  {k[0]} {k[1]}: {v}대")

mid_start = [t for t in output['trains'] if t["origin"] not in ("판암", "반석")]
print(f"\n[중간 출발 열차: {len(mid_start)}대]")
for t in mid_start:   # ← 이 루프를 추가
    print(f"  {t['train_id']}: {t['origin']} {t['origin_depart']} → "
          f"{t['destination']} {t['destination_arrive']} ({t['stop_count']}역)")

mid_end = [t for t in output['trains']
           if t["destination"] not in ("판암", "반석")]
print(f"\n[중간 종착 열차: {len(mid_end)}대]")
for t in mid_end:
    print(f"  {t['train_id']}: {t['origin']} {t['origin_depart']} → "
          f"{t['destination']} {t['destination_arrive']} ({t['stop_count']}역)")

one_stop = [t for t in output['trains'] if t["stop_count"] == 1]
print(f"\n[1역짜리 열차: {len(one_stop)}대]")

# ==========================================
# 10. 검증: 반석 23:42(정부청사) 열차
# ==========================================
print("\n" + "="*60)
print("[검증] 반석 23:42 출발 열차 (평일 상행)")
print("="*60)
for t in output['trains']:
    if (t['day_type']=='평일' and t['direction']=='상행'
            and t['origin']=='반석' and t['origin_depart']=='23:42'):
        print(f"{t['train_id']}: {t['origin']} {t['origin_depart']} → "
              f"{t['destination']} {t['destination_arrive']} ({t['stop_count']}역)")
        for s in t['stops']:
            print(f"    {s['station']} {s['time']}")
        break