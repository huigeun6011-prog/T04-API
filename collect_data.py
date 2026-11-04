import os
import time
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

SERVICE_KEY = os.getenv("SUBWAY_API_KEY")
BASE_URL = "https://apis.data.go.kr/B554695/TicketTypeTrafficSVC/getTicketTypeTraffic01"
DATA_DIR = "./data/raw/subway"

os.makedirs(DATA_DIR, exist_ok=True)

def fetch_page(date_str: str, page_no: int) -> str:
    params = {
        "serviceKey": SERVICE_KEY,
        "startDate": date_str,
        "endDate": date_str,
        "pageNo": page_no,
        "numOfRows": 100
    }
    response = requests.get(BASE_URL, params=params, timeout=30)
    response.raise_for_status()
    return response.text

def parse_total_count(xml_text: str) -> int:
    try:
        root = ET.fromstring(xml_text)
        total_count_elem = root.find(".//totalCount")
        if total_count_elem is not None:
            return int(total_count_elem.text or 0)
    except Exception:
        pass
    return 0

def parse_result_code(xml_text: str) -> str:
    try:
        root = ET.fromstring(xml_text)
        result_code_elem = root.find(".//resultCode")
        if result_code_elem is not None:
            return result_code_elem.text or ""
    except Exception:
        pass
    return ""

def save_xml(date_str: str, xml_text: str, page_no: int):
    filename = f"{DATA_DIR}/{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}.xml"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(xml_text)
    print(f"Saved: {filename} (page {page_no})")

def main():
    start_date = datetime(2025, 11, 1)
    end_date = datetime(2026, 7, 31)

    current_date = start_date
    while current_date <= end_date:
        date_str = current_date.strftime("%Y%m%d")
        print(f"\n=== Collecting data for {date_str} ===")

        page_no = 1
        all_xml = ""

        while True:
            print(f"  Requesting page {page_no}...")
            try:
                xml_text = fetch_page(date_str, page_no)
                result_code = parse_result_code(xml_text)

                if result_code != "00":
                    print(f"  Error: resultCode={result_code}")
                    break

                total_count = parse_total_count(xml_text)
                print(f"  Total count: {total_count}")

                if page_no == 1:
                    all_xml = xml_text
                else:
                    root = ET.fromstring(all_xml)
                    items = root.find(".//items")
                    if items is not None:
                        new_root = ET.fromstring(xml_text)
                        new_items = new_root.find(".//items")
                        if new_items is not None:
                            for item in new_items.findall("item"):
                                items.append(item)

                num_rows = 100
                if page_no * num_rows >= total_count:
                    break

                page_no += 1
                time.sleep(0.3)

            except Exception as e:
                print(f"  Error fetching page {page_no}: {e}")
                break

        if all_xml:
            save_xml(date_str, all_xml, page_no)

        current_date += timedelta(days=1)
        time.sleep(0.5)

    print("\n=== Collection complete ===")

if __name__ == "__main__":
    main()