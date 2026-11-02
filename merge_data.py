import os
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

WEATHER_DIR = "./data/weather_sep"
SUBWAY_DIR = "./data/subway_sep"
MERGED_DIR = "./data/merged_sep"

os.makedirs(MERGED_DIR, exist_ok=True)

def load_weather(date_str: str) -> dict:
    path = os.path.join(WEATHER_DIR, f"{date_str}.json")
    if not os.path.exists(path):
        print(f"  Weather file not found: {path}")
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def parse_subway_xml(date_str: str) -> dict:
    path = os.path.join(SUBWAY_DIR, f"{date_str}.xml")
    if not os.path.exists(path):
        print(f"  Subway file not found: {path}")
        return None
    
    tree = ET.parse(path)
    root = tree.getroot()
    
    station_hourly = {}
    
    for item in root.findall(".//item"):
        entry_flag = item.find("entryFlag")
        if entry_flag is None or entry_flag.text != "0":
            continue
        
        station_no = item.find("stationNo")
        if station_no is None:
            continue
        station_no = station_no.text
        
        if station_no not in station_hourly:
            station_hourly[station_no] = {hour: 0 for hour in range(24)}
        
        for hour in range(24):
            cnt_elem = item.find(f"cnt{hour:02d}")
            if cnt_elem is not None and cnt_elem.text:
                station_hourly[station_no][hour] += int(cnt_elem.text)
    
    return station_hourly

def merge_data(date_str: str) -> dict:
    weather_data = load_weather(date_str)
    if weather_data is None:
        return None
    
    station_hourly = parse_subway_xml(date_str)
    if station_hourly is None:
        return None
    
    hourly = weather_data.get("hourly", {})
    times = hourly.get("time", [])
    precipitation = hourly.get("precipitation", [])
    snowfall = hourly.get("snowfall", [])
    temperature = hourly.get("temperature_2m", [])
    
    if len(times) != 24 or len(precipitation) != 24 or len(snowfall) != 24 or len(temperature) != 24:
        print(f"  Invalid weather data for {date_str}")
        return None
    
    all_stations = sorted(station_hourly.keys())
    
    hourly_data = []
    for hour in range(24):
        subway_list = []
        for station_no in all_stations:
            boardings = station_hourly[station_no].get(hour, 0)
            subway_list.append({
                "station_no": station_no,
                "boardings": boardings
            })
        
        hourly_data.append({
            "hour": hour,
            "weather": {
                "precipitation": precipitation[hour],
                "snowfall": snowfall[hour],
                "temperature_2m": temperature[hour]
            },
            "subway": subway_list
        })
    
    return {
        "date": date_str,
        "hourly_data": hourly_data
    }

def save_merged(date_str: str, data: dict):
    path = os.path.join(MERGED_DIR, f"{date_str}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Saved: {path}")

def main():
    start_date = datetime(2026, 9, 1)
    end_date = datetime(2026, 9, 30)
    
    current_date = start_date
    while current_date <= end_date:
        date_str = current_date.strftime("%Y-%m-%d")
        print(f"Merging {date_str}...")
        
        merged = merge_data(date_str)
        if merged:
            save_merged(date_str, merged)
        else:
            print(f"  Skipped {date_str} (missing data)")
        
        current_date += timedelta(days=1)
    
    print("\n=== Merge complete ===")

if __name__ == "__main__":
    main()