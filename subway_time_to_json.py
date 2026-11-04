import pandas as pd
import json
from datetime import timedelta
from collections import Counter

# ==========================================
# 1. 파일 로드
# ==========================================
FILE_PATH = "./data/raw/subway_time/대전교통공사_열차운행 상황 및 시각표_20250930.csv"

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
# 2. 역 순서 및 역간 소요시간 정의
# ==========================================
stations = [
    "판암", "신흥", "대동", "대전", "중앙로", "중구청",
    "서대전네거리", "오룡", "용문", "탄방", "시청", "정부청사",
    "갈마", "월평", "갑천", "유성온천", "구암", "현충원",
    "월드컵경기장", "노은", "지족", "반석"
]

down_seq = stations                     # 판암 → 반석
up_seq   = list(reversed(stations))     # 반석 → 판암

# 인접 역 소요 시간(분) — 직전 역 기준
base_times = {
    "판암": 2, "신흥": 2, "대동": 2, "대전": 2, "중앙로": 1, "중구청": 2,
    "서대전네거리": 2, "오룡": 2, "용문": 3, "탄방": 1, "시청": 2, "정부청사": 2,
    "갈마": 2, "월평": 2, "갑천": 2, "유성온천": 2, "구암": 2, "현충원": 2,
    "월드컵경기장": 2, "노은": 2, "지족": 2, "반석": 0
}

MIN_GAP, MAX_GAP = 1, 4   # 인접 역 연결 시 허용 시간창(분)

# ==========================================
# 3. 유틸리티
# ==========================================
def parse_time(hour, minute_str):
    """24시대도 24h로 유지 → 시간 축이 단조 증가하도록"""
    h, m = int(hour), int(minute_str)
    return timedelta(hours=h, minutes=m)

def fmt_td(td):
    total = int(td.total_seconds() // 60)
    h, m = divmod(total, 60)
    return f"{h:02d}:{m:02d}"

def add_minutes(hhmm: str, minutes: int) -> str:
    h, m = map(int, hhmm.split(':'))
    total = h * 60 + m + minutes
    return f"{total//60:02d}:{total%60:02d}"

def get_departures(station_name, direction, day_type):
    """
    해당 역/방향/요일의 출발 시각 리스트 반환.
    원본에 '48(판암)'처럼 행선지 표시가 있으면 (시각, 행선지) 튜플로 반환.
    """
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
        for m_str in minutes_str.split():
            if '(' in m_str:
                base, tail = m_str.split('(', 1)
                dest = tail.rstrip(')')
            else:
                base, dest = m_str, None
            if base.isdigit():
                result.append((parse_time(hour, base), dest))
    return result

# ==========================================
# 4. 열차 인스턴스 복원 (연결 그래프 방식)
# ==========================================
def build_trains(seq, direction, day_type):
    """
    seq: 역 순서 리스트 (출발역 → 종착역)
    각 역의 모든 출발 시각을 노드로 보고, 인접 역 간 1~4분 차이로 연결.
    연결 요소(연결된 노드 체인) = 하나의 열차.
    """
    per_station = {}
    for st in seq:
        per_station[st] = get_departures(st, direction, day_type)

    next_map = {}   # 노드 → 다음 노드
    prev_map = {}   # 노드 → 이전 노드

    for i in range(len(seq) - 1):
        cur_st, nxt_st = seq[i], seq[i + 1]
        cur_list = per_station[cur_st]
        nxt_times_sorted = sorted([t for t, _ in per_station[nxt_st]])

        for t, dest in cur_list:
            # 행선지 표시가 있는 열차는 다른 노선/단축 열차 → 연결 스킵
            if dest is not None:
                continue
            lo = t + timedelta(minutes=MIN_GAP)
            hi = t + timedelta(minutes=MAX_GAP)
            candidates = [nt for nt in nxt_times_sorted if lo <= nt <= hi]
            if candidates:
                chosen = candidates[0]
                next_map[(i, t)] = (i + 1, chosen)
                prev_map[(i + 1, chosen)] = (i, t)

    # 시작 노드 = prev_map에 없는 노드 (열차의 첫 정차역)
    all_nodes = set()
    for i, st in enumerate(seq):
        for t, dest in per_station[st]:
            if dest is None:
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

    # 남은 노드(중간 종착 등)는 1역짜리 열차로 처리
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
# 6. 열차 ID 부여 + JSON 직렬화
# ==========================================
all_trains.sort(key=lambda tr: (
    tr["day_type"],
    tr["direction"],
    tr["path"][0][1],
))

output = {"trains": []}
for idx, tr in enumerate(all_trains, start=1):
    first_st, first_t = tr["path"][0]
    last_st,  last_t  = tr["path"][-1]
    train_id = f"{tr['day_type']}-{tr['direction']}-{idx:03d}"

    stops = [
        {"station": st, "time": fmt_td(t)}
        for st, t in tr["path"]
    ]
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
# 7. 종착역 보간
# ==========================================
# CSV에 판암(상행)·반석(하행) 도착 데이터가 없으므로
# 직전 역 출발 시각 + base_times 로 종착역 도착 시각을 계산해 추가한다.

TERMINAL = {
    "하행": {"prev": "지족", "dest": "반석"},
    "상행": {"prev": "신흥", "dest": "판암"},
}

interpolated_count = 0
for t in output['trains']:
    if t["stop_count"] >= 22:
        continue
    info = TERMINAL.get(t["direction"])
    if not info:
        continue
    if t["destination"] != info["prev"]:
        continue

    gap = base_times.get(info["prev"], 2)
    terminal_time = add_minutes(t["destination_arrive"], gap)

    t["stops"].append({"station": info["dest"], "time": terminal_time})
    t["destination"] = info["dest"]
    t["destination_arrive"] = terminal_time
    t["stop_count"] = len(t["stops"])
    t["interpolated"] = True
    interpolated_count += 1

print(f"종착역 보간 적용: {interpolated_count}대")

# ==========================================
# 8. JSON 저장
# ==========================================
with open("trains.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)
print("trains.json 저장 완료")

# ==========================================
# 9. 요약 통계
# ==========================================
print(f"\n총 열차 수: {len(output['trains'])}")

dir_count = Counter((t["day_type"], t["direction"]) for t in output["trains"])
print("\n[방향별 열차 수]")
for k, v in sorted(dir_count.items()):
    print(f"  {k[0]} {k[1]}: {v}대")

full = [t for t in output['trains'] if t["stop_count"] == 22]
full_by = Counter((t["day_type"], t["direction"]) for t in full)
print(f"\n[풀주행(22역) 열차: {len(full)}대]")
for k, v in sorted(full_by.items()):
    print(f"  {k[0]} {k[1]}: {v}대")

mid_start = [t for t in output['trains'] if t["origin"] not in ("판암", "반석")]
print(f"\n[중간 출발 열차: {len(mid_start)}대]")
for t in mid_start:
    print(f"  {t['train_id']}: {t['origin']} {t['origin_depart']} → "
          f"{t['destination']} {t['destination_arrive']} ({t['stop_count']}역)")

mid_end = [t for t in output['trains']
           if t["stop_count"] < 22 and t["origin"] in ("판암", "반석")]
print(f"\n[중간 종착 열차(보간 미적용): {len(mid_end)}대]")
for t in mid_end[:10]:
    print(f"  {t['train_id']}: {t['origin']} {t['origin_depart']} → "
          f"{t['destination']} {t['destination_arrive']} ({t['stop_count']}역)")