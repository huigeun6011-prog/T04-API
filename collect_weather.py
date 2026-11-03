import os
import time
import json
import requests
from datetime import datetime, timedelta

BASE_URL = "https://archive-api.open-meteo.com/v1/archive"
LATITUDE = 36.35
LONGITUDE = 127.38
DATA_DIR = "./data/weather"

os.makedirs(DATA_DIR, exist_ok=True)

def fetch_weather(date_str: str) -> dict:
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "start_date": date_str,
        "end_date": date_str,
        "hourly": "precipitation,snowfall,temperature_2m",
        "timezone": "Asia/Seoul"
    }
    response = requests.get(BASE_URL, params=params, timeout=30)
    response.raise_for_status()
    return response.json()

def parse_hourly_data(data: dict, date_str: str) -> dict:
    hourly = data.get("hourly", {})
    if not hourly:
        return None
    
    times = hourly.get("time", [])
    precipitation = hourly.get("precipitation", [])
    snowfall = hourly.get("snowfall", [])
    temperature = hourly.get("temperature_2m", [])
    
    if not times or len(times) != 24:
        return None
    
    return {
        "date": date_str,
        "hourly": {
            "time": times,
            "precipitation": precipitation,
            "snowfall": snowfall,
            "temperature_2m": temperature
        }
    }

def save_json(date_str: str, weather_data: dict):
    filename = f"{DATA_DIR}/{date_str}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(weather_data, f, ensure_ascii=False, indent=2)
    print(f"Saved: {filename}")

def main():
    start_date = datetime(2026, 8, 1)
    end_date = datetime(2026, 8, 31)

    current_date = start_date
    while current_date <= end_date:
        date_str = current_date.strftime("%Y-%m-%d")
        print(f"Fetching hourly weather for {date_str}...")
        
        try:
            data = fetch_weather(date_str)
            weather_data = parse_hourly_data(data, date_str)
            
            if weather_data:
                save_json(date_str, weather_data)
            else:
                print(f"  No data found for {date_str}")
                
        except Exception as e:
            print(f"  Error fetching {date_str}: {e}")
        
        current_date += timedelta(days=1)
        time.sleep(0.7)

    print("\n=== Hourly weather collection complete ===")

if __name__ == "__main__":
    main()