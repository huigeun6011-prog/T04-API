"""대전 1호선 승하차 XML 을 날짜별로 받아 data/raw/subway/YYYY-MM-DD.xml 로 저장한다(백필).

collect_data.py 와 같은 호출 방식(날짜 하나씩 startDate=endDate, numOfRows=100, 페이지 합치기)이다.
- 키: 환경변수 SUBWAY_API_KEY 또는 루트 .env. 값은 출력·기록하지 않는다.
- resultCode != 00, items 비어 있음, 중간 페이지 실패면 그 날짜는 저장하지 않는다(부분 저장 금지).
- 임시 파일에 쓴 뒤 rename. 이미 있는 파일은 건너뛴다(--force 로 재수집).

사용: .venv/Scripts/python.exe scripts/utils/backfill_subway.py --start 2026-11-03 --end 2026-11-22
"""
import argparse
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote, unquote

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "raw" / "subway"
BASE_URL = "https://apis.data.go.kr/B554695/TicketTypeTrafficSVC/getTicketTypeTraffic01"
NUM_OF_ROWS = 100
PAGE_GAP = 0.5
DATE_GAP = 1.0


def redact(text, key: str) -> str:
    """로그에 키와 URL 이 남지 않게 한다."""
    out = str(text)
    if key:
        for secret in sorted({key, quote(key, safe=""), unquote(key)}, key=len, reverse=True):
            if secret:
                out = out.replace(secret, "<redacted>")
    out = re.sub(r"service_?key=[^&\s\"'<>]*", "serviceKey=<redacted>", out, flags=re.I)
    return re.sub(r"https?://[^\s\"'<>]+", "<url>", out)


RETRY_WAITS = (3, 8, 15)  # 일시적 오류(5xx, 타임아웃, 연결 오류)일 때만 재시도


def fetch_page(day: str, page_no: int, key: str) -> ET.Element:
    compact = day.replace("-", "")
    params = {"serviceKey": key, "startDate": compact, "endDate": compact,
              "pageNo": page_no, "numOfRows": NUM_OF_ROWS}
    for attempt in range(len(RETRY_WAITS) + 1):
        try:
            res = requests.get(BASE_URL, params=params, timeout=30)
            if res.status_code >= 500 or res.status_code == 429:
                res.raise_for_status()
            res.raise_for_status()
            return ET.fromstring(res.text)
        except (requests.Timeout, requests.ConnectionError) as e:
            err = e
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            if not (status >= 500 or status == 429):
                raise
            err = e
        if attempt == len(RETRY_WAITS):
            raise err
        time.sleep(RETRY_WAITS[attempt])


def collect_day(day: str, key: str) -> bytes:
    """하루치 전체 페이지를 합친 XML 바이트. 어떤 이상이든 예외."""
    merged = None
    count = 0
    page_no = 1
    while True:
        root = fetch_page(day, page_no, key)
        code = (root.findtext(".//resultCode") or "").strip()
        if code != "00":
            raise RuntimeError(f"resultCode={code or '없음'}")
        total = int(root.findtext(".//totalCount") or 0)
        items = root.findall(".//items/item")
        if not items:
            raise RuntimeError("items 비어 있음(미공개 또는 자료 없음)")
        if merged is None:
            merged = root
        else:
            target = merged.find(".//items")
            for item in items:
                target.append(item)
        count += len(items)
        # 이 API 는 응답에 totalCount 가 없고 numOfRows 와 무관하게 하루치를 한 번에 준다
        # (기존 data/raw/subway 원본도 totalCount 없음). 그때는 첫 페이지를 전체로 본다.
        if total <= 0 or page_no * NUM_OF_ROWS >= total:
            break
        page_no += 1
        time.sleep(PAGE_GAP)
    if total > 0 and count != total:
        raise RuntimeError(f"받은 item 수 {count} != totalCount {total}")
    return ET.tostring(merged, encoding="utf-8", xml_declaration=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD")
    ap.add_argument("--force", action="store_true", help="이미 있는 파일도 다시 받는다")
    args = ap.parse_args()
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    if start > end:
        ap.error("--start 가 --end 보다 늦다")
    load_dotenv(ROOT / ".env")
    key = os.getenv("SUBWAY_API_KEY")
    if not key:
        print("SUBWAY_API_KEY 가 환경변수나 .env 에 없다.", file=sys.stderr)
        return 2
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    problems = []
    called = False
    d = start
    while d <= end:
        day = d.isoformat()
        d += timedelta(days=1)
        out = DATA_DIR / f"{day}.xml"
        if out.exists() and not args.force:
            print(f"{day} SKIP(이미 있음)")
            continue
        if called:
            time.sleep(DATE_GAP)
        called = True
        try:
            data = collect_day(day, key)
        except Exception as e:
            print(f"{day} 저장 안 함: " + redact(f"{type(e).__name__}: {e}", key))
            problems.append(day)
            continue
        tmp = out.with_suffix(".xml.tmp")
        tmp.write_bytes(data)
        tmp.replace(out)
        print(f"{day} SAVED ({len(data)} bytes)")
    if problems:
        print("저장하지 못한 날짜: " + ", ".join(problems))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
