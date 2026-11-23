"""대전 시간별 날씨(Open-Meteo, 키 불필요)를 원본 폴더 data/raw/weather/YYYY-MM-DD.json 으로 채우고,
정적 사본 static-web/data/weather/ 는 여기서 만들지 않는다(생성물, 커밋 안 함): node scripts/sync_static_data.mjs

원본 형식(기존 파일과 같다): {"date","hourly":{"time","precipitation","snowfall","temperature_2m"}}, indent=2, CRLF, 끝 줄바꿈 없음.
정적 사본 형식(scripts/build_static_web.py 와 같다): {"hourly":{"time","temperature_2m","precipitation","snowfall"}} 공백 없는 JSON.
archive API 만 쓴다. 최근 며칠은 값이 비어 있을 수 있고, 그러면 저장하지 않고 '미수집'으로 보고한다(다시 실행하면 재시도).
24개 값이 모두 숫자가 아니면 저장하지 않는다. 이미 있는 원본은 건너뛴다(--force 로 재수집).

사용: .venv/Scripts/python.exe scripts/utils/backfill_weather.py --start 2026-11-03 --end 2026-11-22
"""
import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw" / "weather"
LAT, LON = 36.35, 127.38
VARS = ("temperature_2m", "precipitation", "snowfall")
# '지난 날의 기록'(archive)만 인정한다. 값이 비면 저장하지 않고 미수집으로 보고한다(forecast 대체 없음).
SOURCES = (("archive", "https://archive-api.open-meteo.com/v1/archive"),)
GAP_SECONDS = 2.5


def fetch(url: str, day: str) -> dict:
    params = {
        "latitude": LAT, "longitude": LON, "start_date": day, "end_date": day,
        "hourly": ",".join(VARS), "timezone": "Asia/Seoul",
    }
    res = requests.get(url, params=params, timeout=30)
    res.raise_for_status()
    return res.json()


def validate(payload, day: str):
    """24개 값이 모두 숫자면 저장용 dict, 아니면 None."""
    hourly = (payload or {}).get("hourly") or {}
    times = hourly.get("time") or []
    if len(times) != 24 or any(not str(t).startswith(day) for t in times):
        return None
    out = {"time": list(times)}
    for name in VARS:
        values = hourly.get(name) or []
        if len(values) != 24 or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in values):
            return None
        out[name] = list(values)
    return {"hourly": out}


def raw_text(day: str, hourly: dict) -> str:
    doc = {"date": day, "hourly": {k: hourly[k] for k in ("time", "precipitation", "snowfall", "temperature_2m")}}
    return json.dumps(doc, indent=2, ensure_ascii=False, allow_nan=False).replace(chr(10), chr(13) + chr(10))


def static_text(hourly: dict) -> str:  # 참고용: sync_static_data.mjs 가 만드는 사본 형식(build_static_web.py 와 같다)
    doc = {"hourly": {k: hourly[k] for k in ("time", "temperature_2m", "precipitation", "snowfall")}}
    return json.dumps(doc, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def save_atomic(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_bytes(text.encode("utf-8"))  # 줄바꿈을 그대로 쓴다(원본은 CRLF)
    tmp.replace(path)


def save_day(day: str, doc: dict):
    save_atomic(RAW_DIR / f"{day}.json", raw_text(day, doc["hourly"]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD")
    ap.add_argument("--force", action="store_true", help="이미 있는 파일도 다시 받는다")
    args = ap.parse_args()
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    if start > end:
        ap.error("--start 가 --end 보다 늦다")
    failed = []
    called = False
    d = start
    while d <= end:
        day = d.isoformat()
        d += timedelta(days=1)
        path = RAW_DIR / f"{day}.json"  # 존재 판정은 원본 폴더 기준
        if path.exists() and not args.force:
            print(f"{day} SKIP(이미 있음)")
            continue
        doc, used = None, None
        for name, url in SOURCES:
            if called:
                time.sleep(GAP_SECONDS)
            called = True
            try:
                doc = validate(fetch(url, day), day)
            except Exception as e:  # 네트워크·JSON 오류
                print(f"{day} {name} 실패: {type(e).__name__}", file=sys.stderr)
                doc = None
            if doc:
                used = name
                break
        if doc is None:
            print(f"{day} FAIL(날씨 미수집: archive 에 24개 숫자 값이 없어 저장 안 함)")
            failed.append(day)
            continue
        save_day(day, doc)
        print(f"{day} SAVED ({used})")
    print("정적 사본은 node scripts/sync_static_data.mjs 로 만든다.")
    if failed:
        print("저장하지 못한 날짜: " + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
