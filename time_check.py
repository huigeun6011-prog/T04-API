import json
import pandas as pd

CSV_PATH  = "./data/raw/subway_time/대전교통공사_열차운행 상황 및 시각표_20250930.csv"
JSON_PATH = "subway_time.json"

# ==========================================
# 1. CSV 총 시각 개수 세기
# ==========================================
for enc in ['cp949', 'euc-kr', 'utf-8-sig']:
    try:
        df = pd.read_csv(CSV_PATH, encoding=enc)
        break
    except UnicodeDecodeError:
        continue

csv_total = 0
csv_by_group = {}   # (역명, 방향, 요일) → 토큰 개수

for _, row in df.iterrows():
    key = (row['역명'], row['운행방향'], row['휴일구분'])
    minutes_str = str(row['동 시간대 분'])
    if pd.isna(minutes_str) or minutes_str == 'nan':
        continue
    tokens = minutes_str.split()
    csv_total += len(tokens)
    csv_by_group[key] = csv_by_group.get(key, 0) + len(tokens)

print(f"[CSV] 총 시각 토큰 수: {csv_total}")

# ==========================================
# 2. JSON 총 정차 시각 개수 세기
# ==========================================
with open(JSON_PATH, encoding='utf-8') as f:
    data = json.load(f)

json_total = sum(t['stop_count'] for t in data['trains'])

# 역명 + 방향 + 요일별 JSON 시각 수 (보간 제외)
json_by_group = {}
interpolated_total = 0

for t in data['trains']:
    day = t['day_type']
    direction = t['direction']
    for stop in t['stops']:
        st = stop['station']
        # 보간으로 추가된 종착역인지 확인
        is_interp = (
            t.get('interpolated', False)
            and stop['station'] == t['destination']
            and stop['time'] == t['destination_arrive']
        )
        if is_interp:
            interpolated_total += 1
            continue
        key = (f"{st}역", direction, day)
        json_by_group[key] = json_by_group.get(key, 0) + 1

print(f"[JSON] 총 정차 시각 수: {json_total}")
print(f"[JSON] 보간으로 추가된 시각 수: {interpolated_total}")
print(f"[JSON] 원본 대응 시각 수 (총 − 보간): {json_total - interpolated_total}")

# ==========================================
# 3. 비교
# ==========================================
print("\n" + "="*60)
print(f"CSV 총 시각 수:              {csv_total}")
print(f"JSON 원본 대응 시각 수:      {json_total - interpolated_total}")
print(f"차이 (JSON − CSV):           {(json_total - interpolated_total) - csv_total}")
print("="*60)

if (json_total - interpolated_total) == csv_total:
    print("✅ 원본 데이터 100% 일치 (누락·중복 없음)")
else:
    print("⚠️ 불일치 — 상세 분석 필요")

# ==========================================
# 4. 그룹별(역·방향·요일) 불일치 상세
# ==========================================
print("\n[그룹별 불일치 상세] (CSV ≠ JSON인 것만)")
mismatches = []
all_keys = set(csv_by_group.keys()) | set(json_by_group.keys())
for k in sorted(all_keys):
    c = csv_by_group.get(k, 0)
    j = json_by_group.get(k, 0)
    if c != j:
        mismatches.append((k, c, j, j - c))

if not mismatches:
    print("  그룹별로도 모두 일치 ✅")
else:
    print(f"  {'역명':<18} {'방향':<6} {'요일':<6} {'CSV':>5} {'JSON':>5} {'차이':>5}")
    for (st, d, day), c, j, diff in mismatches:
        print(f"  {st:<18} {d:<6} {day:<6} {c:>5} {j:>5} {diff:>+5}")
    print(f"\n  총 불일치 그룹: {len(mismatches)}개")