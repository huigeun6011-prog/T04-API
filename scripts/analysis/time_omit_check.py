import pandas as pd
import json
from collections import defaultdict

CSV_PATH  = "../../data/raw/subway_time/대전교통공사_열차운행 상황 및 시각표_20250930.csv"
JSON_PATH = "../../subway_time.json"

# ==========================================
# CSV 로드
# ==========================================
for enc in ['cp949', 'euc-kr', 'utf-8-sig']:
    try:
        df = pd.read_csv(CSV_PATH, encoding=enc)
        break
    except UnicodeDecodeError:
        continue

# ==========================================
# JSON 로드
# ==========================================
with open(JSON_PATH, encoding='utf-8') as f:
    data = json.load(f)

# ==========================================
# 1. JSON을 (원본, 보간)으로 분리
# ==========================================
# 보간 판별: interpolated=true 이고 마지막 stop이고 그게 destination일 때
json_original = set()      # (day, dir, station, time)
json_interpolated = set()

for t in data['trains']:
    for i, s in enumerate(t['stops']):
        key = (t['day_type'], t['direction'], s['station'], s['time'])
        is_interp = (
            t.get('interpolated', False)
            and i == len(t['stops']) - 1
            and s['station'] == t['destination']
        )
        if is_interp:
            json_interpolated.add(key)
        else:
            json_original.add(key)

# ==========================================
# 2. CSV의 모든 시각 수집
# ==========================================
csv_set = set()
csv_total = 0
for _, row in df.iterrows():
    station = row['역명'].replace('역', '')
    direction = row['운행방향']
    day = row['휴일구분']
    hour = int(row['시간대'])
    minutes_str = str(row['동 시간대 분'])
    if pd.isna(minutes_str) or minutes_str == 'nan':
        continue
    for tok in minutes_str.split():
        base = tok.split('(')[0]
        if base.isdigit():
            time_str = f"{hour:02d}:{int(base):02d}"
            csv_set.add((day, direction, station, time_str))
            csv_total += 1

# ==========================================
# 3. 비교
# ==========================================
print("=" * 70)
print("[기본 수치]")
print("=" * 70)
print(f"  CSV 총 토큰:              {csv_total}")
print(f"  CSV 고유 시각:            {len(csv_set)}")
print(f"  JSON 원본 시각:           {len(json_original)}")
print(f"  JSON 보간 시각:           {len(json_interpolated)}")
print(f"  JSON 총 시각:             {len(json_original) + len(json_interpolated)}")

# ==========================================
# 4. 검증 A: JSON 원본 = CSV
# ==========================================
print("\n" + "=" * 70)
print("[검증 A] JSON 원본 vs CSV")
print("=" * 70)

missing = csv_set - json_original   # CSV에 있는데 JSON 원본에 없음
extra   = json_original - csv_set   # JSON 원본에 있는데 CSV에 없음

print(f"  CSV에 있지만 JSON 원본에 없음: {len(missing)}건")
print(f"  JSON 원본에 있지만 CSV에 없음: {len(extra)}건")

if missing:
    grouped = defaultdict(list)
    for day, direction, st, tm in sorted(missing):
        grouped[(day, direction)].append((st, tm))
    for (day, direction), items in sorted(grouped.items()):
        print(f"\n  [{day} {direction}] {len(items)}건")
        for st, tm in items[:10]:
            print(f"    {st} {tm}")
        if len(items) > 10:
            print(f"    ... 외 {len(items)-10}건")

if extra:
    print("\n  [JSON 원본에만 있는 시각]")
    for key in sorted(extra)[:10]:
        print(f"    {key}")

if not missing and not extra:
    print("  ✅ JSON 원본 = CSV (완벽 일치)")

# ==========================================
# 5. 검증 B: 보간 시각이 CSV에 없는지
# ==========================================
print("\n" + "=" * 70)
print("[검증 B] 보간 시각이 CSV에 있는지")
print("=" * 70)

interp_in_csv = json_interpolated & csv_set
print(f"  보간 시각 중 CSV에도 있는 것: {len(interp_in_csv)}건")

if interp_in_csv:
    print("  ⚠️ 보간했는데 사실 CSV에 있던 시각:")
    for key in sorted(interp_in_csv)[:10]:
        print(f"    {key}")
else:
    print("  ✅ 보간 시각은 모두 CSV에 없는 시각")

# ==========================================
# 6. 검증 C: 보간 시각의 역명이 올바른지
# ==========================================
# 모든 보간 시각은 "마지막 역의 다음 역"이어야 함
print("\n" + "=" * 70)
print("[검증 C] 보간 시각이 '마지막 역의 다음 역'인지")
print("=" * 70)

stations = [
    "판암", "신흥", "대동", "대전", "중앙로", "중구청",
    "서대전네거리", "오룡", "용문", "탄방", "시청", "정부청사",
    "갈마", "월평", "갑천", "유성온천", "구암", "현충원",
    "월드컵경기장", "노은", "지족", "반석"
]
down_seq = stations
up_seq = list(reversed(stations))

bad_interp = []
for t in data['trains']:
    if not t.get('interpolated', False):
        continue
    seq = up_seq if t['direction'] == '상행' else down_seq
    if len(t['stops']) < 2:
        bad_interp.append((t['train_id'], "stop 1개 이하"))
        continue
    prev_st = t['stops'][-2]['station']
    last_st = t['stops'][-1]['station']
    if prev_st not in seq:
        bad_interp.append((t['train_id'], f"prev={prev_st} seq에 없음"))
        continue
    prev_idx = seq.index(prev_st)
    if prev_idx + 1 >= len(seq):
        bad_interp.append((t['train_id'], f"{prev_st}가 seq의 끝"))
        continue
    expected_next = seq[prev_idx + 1]
    if last_st != expected_next:
        bad_interp.append((t['train_id'],
                           f"prev={prev_st} → last={last_st} (기대: {expected_next})"))

print(f"  보간된 열차 총 {sum(1 for t in data['trains'] if t.get('interpolated'))}대")
print(f"  잘못된 보간: {len(bad_interp)}건")
if bad_interp:
    for tid, msg in bad_interp[:20]:
        print(f"    {tid}: {msg}")
else:
    print("  ✅ 모든 보간이 '마지막 역의 다음 역'으로 올바르게 추가됨")

# ==========================================
# 7. 검증 D: 보간 시각의 '시간'이 base_times와 맞는지
# ==========================================
print("\n" + "=" * 70)
print("[검증 D] 보간 시각 = 마지막 역 시각 + base_times[마지막 역]")
print("=" * 70)

base_times = {
    "판암": 2, "신흥": 2, "대동": 2, "대전": 2, "중앙로": 1, "중구청": 2,
    "서대전네거리": 2, "오룡": 2, "용문": 3, "탄방": 1, "시청": 2, "정부청사": 2,
    "갈마": 2, "월평": 2, "갑천": 2, "유성온천": 2, "구암": 2, "현충원": 2,
    "월드컵경기장": 2, "노은": 2, "지족": 2, "반석": 0
}

def to_min(hhmm):
    h, m = map(int, hhmm.split(':'))
    return h * 60 + m

bad_time = []
for t in data['trains']:
    if not t.get('interpolated', False):
        continue
    prev_time = t['stops'][-2]['time']
    prev_st = t['stops'][-2]['station']
    last_time = t['stops'][-1]['time']
    expected = to_min(prev_time) + base_times.get(prev_st, 2)
    actual = to_min(last_time)
    if expected != actual:
        bad_time.append((t['train_id'], prev_st, prev_time, last_time,
                         f"기대 {expected//60:02d}:{expected%60:02d}"))

print(f"  시간 불일치: {len(bad_time)}건")
if bad_time:
    for item in bad_time[:10]:
        print(f"    {item}")
else:
    print("  ✅ 모든 보간 시각이 base_times와 정확히 일치")

# ==========================================
# 8. 최종 요약
# ==========================================
print("\n" + "=" * 70)
print("[최종 요약]")
print("=" * 70)
checks = [
    ("A. JSON 원본 = CSV", len(missing) == 0 and len(extra) == 0),
    ("B. 보간 시각 ∉ CSV", len(interp_in_csv) == 0),
    ("C. 보간 = 마지막 역의 다음 역", len(bad_interp) == 0),
    ("D. 보간 시간 = base_times", len(bad_time) == 0),
]
for name, ok in checks:
    print(f"  {'✅' if ok else '⚠️'} {name}")

if all(ok for _, ok in checks):
    print("\n🎉 모든 검증 통과")
else:
    print("\n❗ 일부 검증 실패")