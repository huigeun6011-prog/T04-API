import pandas as pd

SRC = "../.././data/raw/subway_time/260330_대전1호선_평일시간표_공식대조수정.xlsx"
OUT = "../.././data/raw/subway_time/대전교통공사_열차운행 상황 및 시각표_20260330.csv"

# 역 순서 (판암 → 반석)
stations = [
    "판암", "신흥", "대동", "대전", "중앙로", "중구청",
    "서대전네거리", "오룡", "용문", "탄방", "시청", "정부청사",
    "갈마", "월평", "갑천", "유성온천", "구암", "현충원",
    "월드컵경기장", "노은", "지족", "반석",
]

raw = pd.read_excel(SRC, header=None)

# 1행 역명: 병합 셀 때문에 NaN → forward fill
stations_row = raw.iloc[0].ffill().tolist()
dir_row      = raw.iloc[1].tolist()

# 역명 정규화: 이미 '역'으로 끝나면 그대로, 아니면 '역' 붙임
def norm_station(name):
    name = str(name).strip()
    if not name:
        return None
    return name if name.endswith("역") else f"{name}역"

# 열 매핑: (열인덱스, 역명, 방향)
col_map = []
for c in range(1, len(stations_row)):
    st = norm_station(stations_row[c])
    if st is None:
        continue
    arrow = str(dir_row[c]).strip()
    if arrow == "→":
        direction = "하행"   # 반석행
    elif arrow == "←":
        direction = "상행"   # 판암행
    else:
        continue
    col_map.append((c, st, direction))

# 3행부터 데이터. A열 수식 캐시 문제 회피: 5시부터 1시간씩
records = []
for r in range(2, len(raw)):
    hour = 5 + (r - 2)
    for c, st, direction in col_map:
        val = raw.iloc[r, c]
        if pd.isna(val):
            continue
        val = str(val).strip()
        if not val:
            continue
        records.append({
            "역명": st,
            "운행방향": direction,
            "휴일구분": "평일",
            "시간대": hour,
            "동 시간대 분": val,
        })

df = pd.DataFrame(records)

# 역 순서 강제 정렬 (판암 → 반석), 같은 역 안에서는 하행 → 상행
df["_역순"] = df["역명"].str.replace("역", "", regex=False).map(
    {s: i for i, s in enumerate(stations)}
)
df["_방향순"] = df["운행방향"].map({"하행": 0, "상행": 1})
df = df.sort_values(["_역순", "_방향순", "시간대"]).drop(columns=["_역순", "_방향순"])

df.to_csv(OUT, index=False, encoding="utf-8-sig")

print(df.head(10))
print("행 수:", len(df))
print("역 순서:", df["역명"].drop_duplicates().tolist())