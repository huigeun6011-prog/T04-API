"""Build web/data/station_profile.json: real average boardings/alightings per station and hour.

Run from any working directory with:
    python scripts/build_web_station_profile.py

Reads data/processed/subway/{date}.json read-only for service days
2024-11-01..2026-11-01. Service-day rule: hours 5..23 come from that day's file,
hour 24 is the next day's hour 0; hours 01-04 are excluded (project decision D-001).
Day type uses the project's own rule (weekend or HOLIDAYS in predict_load.py).
"""

import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from predict_load import HOLIDAYS, STATION_NAMES  # noqa: E402

SRC = ROOT / "data" / "processed" / "subway"
OUT = ROOT / "web" / "data" / "station_profile.json"
FIRST, LAST = date(2024, 11, 1), date(2026, 11, 1)
HOURS = list(range(5, 25))


def day_type(day: date) -> str:
    return "휴일" if day.isoformat() in HOLIDAYS or day.weekday() >= 5 else "평일"


def load(day: date):
    path = SRC / f"{day.isoformat()}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))["stations"]


def main() -> None:
    sums = {t: {n: {k: [0.0] * 20 for k in ("boardings", "alightings")} for n in STATION_NAMES} for t in ("평일", "휴일")}
    counts = {t: {n: [0] * 20 for n in STATION_NAMES} for t in ("평일", "휴일")}
    days = {"평일": 0, "휴일": 0}
    used = []
    day = FIRST
    while day <= LAST:
        today = load(day)
        if today is None:
            day += timedelta(days=1)
            continue
        nxt = load(day + timedelta(days=1))
        kind = day_type(day)
        days[kind] += 1
        used.append(day)
        for idx, name in enumerate(STATION_NAMES):
            code = str(101 + idx)
            for k in ("boardings", "alightings"):
                for pos, hour in enumerate(HOURS):
                    if hour == 24:
                        value = None if nxt is None else nxt.get(code, {}).get(k, {}).get("0")
                    else:
                        value = today.get(code, {}).get(k, {}).get(str(hour))
                    if value is None:
                        continue
                    sums[kind][name][k][pos] += float(value)
                    if k == "boardings":
                        counts[kind][name][pos] += 1
        day += timedelta(days=1)

    stations = {}
    for name in STATION_NAMES:
        stations[name] = {}
        for t in ("평일", "휴일"):
            n = counts[t][name]
            stations[name][t] = {
                k: [round(sums[t][name][k][i] / n[i], 1) if n[i] else None for i in range(20)]
                for k in ("boardings", "alightings")
            }
    result = {
        "hours": HOURS,
        "days": days,
        "date_range": [used[0].isoformat(), used[-1].isoformat()] if used else None,
        "note": "시간별 평균 승차/하차 인원. 24시는 다음 날 0시. 01~04시 제외.",
        "stations": stations,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT} days={days} range={result['date_range']}")


if __name__ == "__main__":
    main()
