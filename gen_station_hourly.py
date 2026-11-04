import json

with open("subway_time.json", encoding="utf-8") as f:
    data = json.load(f)

output = {"평일": {}, "휴일": {}}

for train in data["trains"]:
    day = train["day_type"]
    stops = train["stops"]
    n = len(stops)
    if n == 0:
        continue
    for i, stop in enumerate(stops):
        station = stop["station"]
        hour = int(stop["time"][:2])
        hour_key = str(hour)
        if station not in output[day]:
            output[day][station] = {}
        if hour_key not in output[day][station]:
            output[day][station][hour_key] = {"departures": 0, "passes": 0, "arrivals": 0}
        cell = output[day][station][hour_key]
        if i == 0:
            cell["departures"] += 1
        elif i == n - 1:
            cell["arrivals"] += 1
        else:
            cell["passes"] += 1

with open("station_hourly.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

# summary
total_trains = len(data["trains"])
dep = sum(c["departures"] for d in output.values() for s in d.values() for c in s.values())
arr = sum(c["arrivals"] for d in output.values() for s in d.values() for c in s.values())
pas = sum(c["passes"] for d in output.values() for s in d.values() for c in s.values())
print("trains:", total_trains)
print("departures:", dep, "arrivals:", arr, "passes:", pas)
print("saved station_hourly.json")
