import os
import time
import requests
import xml.etree.ElementTree as ET
from dotenv import load_dotenv

load_dotenv()

SERVICE_KEY = os.getenv("SUBWAY_API_KEY")
BASE_URL = "https://apis.data.go.kr/B554695/TicketTypeTrafficSVC/getTicketTypeTraffic01"
DATA_DIR = "./data/subway_sep"

os.makedirs(DATA_DIR, exist_ok=True)

FAILED_DATES = ["20260902", "20260907", "20260909", "20260925"]

def fetch_page(date_str: str, page_no: int, max_retries: int = 3) -> str:
    params = {
        "serviceKey": SERVICE_KEY,
        "startDate": date_str,
        "endDate": date_str,
        "pageNo": page_no,
        "numOfRows": 100
    }
    
    for attempt in range(max_retries):
        try:
            response = requests.get(BASE_URL, params=params, timeout=60)
            if response.status_code == 503:
                wait_time = (attempt + 1) * 2
                print(f"  503 error, waiting {wait_time}s before retry (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
                continue
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException as e:
            if attempt == max_retries - 1:
                raise
            wait_time = (attempt + 1) * 2
            print(f"  Error: {e}, waiting {wait_time}s before retry")
            time.sleep(wait_time)
    raise Exception(f"Max retries exceeded for {date_str} page {page_no}")

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

def save_xml(date_str: str, xml_text: str):
    filename = f"{DATA_DIR}/{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}.xml"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(xml_text)
    print(f"Saved: {filename}")

def main():
    for date_str in FAILED_DATES:
        print(f"\n=== Retrying {date_str} ===")
        
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
            save_xml(date_str, all_xml)
        else:
            print(f"  Failed to collect data for {date_str}")

        time.sleep(1)

    print("\n=== Retry complete ===")

if __name__ == "__main__":
    main()