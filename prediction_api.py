"""Local recommendation API: python prediction_api.py --port 8000.

Service dates span 05:00 through the following calendar day's 00:59.
The model predicts post-stop train occupancy, not POI visitor counts.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import threading
import time
from datetime import date, datetime, timedelta
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.parse import urlencode
from urllib.request import urlopen
from urllib.error import URLError

import joblib
import numpy as np
import pandas as pd

from predict_load import HOLIDAYS, STATION_NAMES

ROOT = Path(__file__).resolve().parent
FEATURES = ['station_idx', 'hour', 'dir_code', 'is_weekend', 'temp', 'precip', 'snow', 'plan_version']
MODEL_PATH = ROOT / 'outputs/load_predictor.joblib'
CHANGE = '2026-03-30'
STATIONS = []
_model = None
_model_stamp = None
_model_lock = threading.Lock()
_weather_lock = threading.Lock()
_weather_cache = {}
_last_remote_call = 0.0


def stations():
    """Read the same checked-in coordinates used by the map; never read API keys."""
    if not STATIONS:
        source = (ROOT / 'web/app.js').read_text(encoding='utf-8')
        for name, idx, lat, lng in re.findall(r"name:\s*'([^']+)'\s*,\s*idx:\s*(\d+)\s*,\s*lat:\s*([\d.]+)\s*,\s*lng:\s*([\d.]+)", source):
            STATIONS.append(dict(name=name, idx=int(idx), lat=float(lat), lng=float(lng)))
        if len(STATIONS) != 22:
            raise RuntimeError('역 좌표 22개를 읽지 못했습니다.')
    return STATIONS


def service_time(calendar_date, hour):
    """An explicit calendar 00 request belongs to the preceding service date."""
    day = date.fromisoformat(calendar_date)
    if hour == 0:
        return (day - timedelta(days=1)).isoformat(), 24
    if not 5 <= hour <= 24:
        raise ValueError('운행 시간은 05~24시입니다. 달력 00시는 전날 운행일 24시로 변환합니다.')
    return day.isoformat(), hour


def actual_time(service_date, hour, minute=0):
    return datetime.fromisoformat(service_date) + timedelta(hours=hour, minutes=minute)


def holiday(service_date):
    return date.fromisoformat(service_date).weekday() >= 5 or service_date in HOLIDAYS


def get_model():
    global _model, _model_stamp
    stamp = MODEL_PATH.stat().st_mtime_ns
    with _model_lock:
        if _model is None or stamp != _model_stamp:
            _model = joblib.load(MODEL_PATH)
            _model_stamp = stamp
        return _model


@lru_cache(maxsize=2)
def schedule_file(version):
    path = ROOT / f'data/processed/subway_time/subway_time_{version}.json'
    return json.loads(path.read_text(encoding='utf-8'))['trains']


def schedule(service_date):
    is_holiday = holiday(service_date)
    version = '20260330' if service_date >= CHANGE and not is_holiday else '20250930'
    giornata = '휴일' if is_holiday else '평일'
    return [t for t in schedule_file(version) if t['day_type'] == giornata]


def weather_day(calendar_date):
    """Prefer archived local hourly data; serialize remote calls and cache responses."""
    global _last_remote_call
    local = ROOT / f'data/raw/weather/{calendar_date}.json'
    if local.exists():
        return json.loads(local.read_text(encoding='utf-8'))['hourly'], 'local_archive'
    today = datetime.now().date()
    requested = date.fromisoformat(calendar_date)
    if requested > today + timedelta(days=15):
        raise ValueError('날씨 예보 범위는 오늘부터 15일 후까지입니다.')
    ttl = 7 * 86400 if requested < today else 3600
    with _weather_lock:
        cached = _weather_cache.get(calendar_date)
        if cached and time.monotonic() - cached[0] < ttl:
            return cached[1], cached[2]
        pause = 10 - (time.monotonic() - _last_remote_call)
        if pause > 0:
            time.sleep(pause)
        endpoint = 'https://archive-api.open-meteo.com/v1/archive' if requested < today else 'https://api.open-meteo.com/v1/forecast'
        _last_remote_call = time.monotonic()
        try:
            params = urlencode({'latitude': 36.35, 'longitude': 127.38, 'hourly': 'temperature_2m,precipitation,snowfall', 'timezone': 'Asia/Seoul', 'start_date': calendar_date, 'end_date': calendar_date})
            with urlopen(endpoint+'?'+params, timeout=25) as response:
                hourly = json.load(response)['hourly']
        except (URLError, TimeoutError, KeyError, ValueError) as exc:
            raise ValueError('날씨 조회에 실패했습니다. 잠시 후 다시 시도해 주세요.') from exc
        source = 'archive' if requested < today else 'forecast'
        _weather_cache[calendar_date] = (time.monotonic(), hourly, source)
        return hourly, source


def weather_profile(service_date, hours):
    result, sources = {}, set()
    for hour in sorted(set(hours)):
        instant = actual_time(service_date, hour)
        raw, source = weather_day(instant.date().isoformat())
        key = instant.strftime('%Y-%m-%dT%H:00')
        try:
            idx = raw['time'].index(key)
            values = [float(raw[k][idx]) for k in ('temperature_2m', 'precipitation', 'snowfall')]
            if not all(math.isfinite(v) for v in values):
                raise ValueError()
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            raise ValueError(f'{key} 날씨 자료가 없어 예측할 수 없습니다.') from exc
        result[hour] = values
        sources.add(source)
    return result, sorted(sources)


def km(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (a['lat'], a['lng'], b['lat'], b['lng']))
    h = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371 * 2 * math.asin(min(1, math.sqrt(h)))


def nearest(point):
    return min(stations(), key=lambda s: km(point, s))


def predict_profile(service_date, selected_hours, boarding_station):
    trains = schedule(service_date)
    valid = []
    needed_hours = set()
    for train in trains:
        stops = train['stops']
        boarding = next((stop for stop in stops if stop['station'] == boarding_station), None)
        if boarding is None or (int(boarding['time'].split(':')[0]) or 24) not in selected_hours:
            continue
        boarding = next((s for s in stops[:-1] if s['station'] == boarding_station), None)
        if boarding is None or (int(boarding['time'].split(':')[0]) or 24) not in selected_hours:
            continue
        for stop in stops:
            h = int(stop['time'].split(':')[0])
            if h == 0:
                h = 24
            if not 5 <= h <= 24:
                continue
            needed_hours.add(h)
        valid.append(train)
    # Profile includes later stops on a selected train, even after chosen boarding hour.
    weather, sources = weather_profile(service_date, needed_hours)
    features, keys = [], []
    for train in valid:
        for stop in train['stops'][:-1]:
            hour = int(stop['time'].split(':')[0]) or 24
            key = (stop['station'], hour, train['direction'])
            if hour not in weather or key in keys:
                continue
            features.append([STATION_NAMES.index(stop['station']), hour, 0 if train['direction']=='상행' else 1, int(holiday(service_date)), *weather[hour], int(service_date >= CHANGE)])
            keys.append(key)
    model = get_model()
    loads = np.maximum(model.predict(pd.DataFrame(features, columns=FEATURES)), 0) if features else []
    return valid, dict(zip(keys, map(float, loads))), sources


def recommend(payload):
    day = date.fromisoformat(str(payload['date'])).isoformat()
    start, end = int(payload.get('start_hour', 5)), int(payload.get('end_hour', 24))
    if not (5 <= start <= end <= 24):
        raise ValueError('시작·종료 시간은 05~24시이며 시작은 종료보다 늦을 수 없습니다.')
    weight = float(payload.get('quiet_weight', 50))
    if not 0 <= weight <= 100 or weight % 10:
        raise ValueError('한산함 비율은 0~100 사이의 10% 단위여야 합니다.')
    origin = {k: float(payload['origin'][k]) for k in ('lat','lng')}
    if not all(math.isfinite(v) for v in origin.values()) or not (-90 <= origin['lat'] <= 90 and -180 <= origin['lng'] <= 180):
        raise ValueError('출발 좌표가 올바르지 않습니다.')
    board = nearest(origin)
    trains, loads, weather_sources = predict_profile(day, range(start, end+1), board['name'])
    pois = json.loads((ROOT/'web/data/pois.json').read_text(encoding='utf-8'))
    candidates = []
    # Best timetable-feasible train per hour and alighting station; all segment post-stop loads.
    trips = {}
    for train in trains:
        stops = train['stops']
        names = [s['station'] for s in stops]
        if board['name'] not in names:
            continue
        i = names.index(board['name'])
        departure = stops[i]['time']
        hour = int(departure.split(':')[0]) or 24
        if not start <= hour <= end:
            continue
        for j in range(i+1, len(stops)):
            segment = []
            for stop in stops[i:j]:
                sh = int(stop['time'].split(':')[0]) or 24
                segment.append(loads[(stop['station'], sh, train['direction'])])
            trip = dict(hour=hour, departure_time=departure, arrival_time=stops[j]['time'], direction=train['direction'], train_id=train['train_id'], mean_load=round(sum(segment)/len(segment),1), max_load=round(max(segment),1), no_train=False)
            key = (names[j], hour)
            if key not in trips or (trip['mean_load'], trip['departure_time']) < (trips[key]['mean_load'], trips[key]['departure_time']):
                trips[key] = trip
    category = payload.get('category','all')
    for poi in pois:
        if not poi.get('has_coordinates') or (category != 'all' and poi['facility_type'] != category):
            continue
        point = dict(lat=float(poi['latitude']),lng=float(poi['longitude']))
        alight = nearest(point)
        base = dict(poi=poi, boarding_station=board, alighting_station=alight, distance_km=round(km(origin,point),3), walking_distance_km=round(km(origin,board)+km(point,alight),3), opening_hours=None)
        if alight['idx'] == board['idx']:
            candidates.append(dict(**base,hour=None,departure_time=None,arrival_time=None,direction=None,train_id=None,mean_load=None,max_load=None,no_train=True))
        else:
            candidates.extend(dict(**base,**trip) for (station,h),trip in trips.items() if station==alight['name'])
    max_distance = max((c['distance_km'] for c in candidates), default=1) or 1
    max_load = max((c['mean_load'] or 0 for c in candidates), default=1) or 1
    for c in candidates:
        quiet = 0.5 if c['no_train'] else 1-c['mean_load']/max_load
        near = 1-c['distance_km']/max_distance
        c['quiet_score'] = round(quiet*100,1)
        c['distance_score'] = round(near*100,1)
        c['score'] = round(weight*quiet+(100-weight)*near,2)
        c['service_date'] = day
        c['calendar_departure'] = actual_time(day,c['hour'],int(c['departure_time'].split(':')[1])).isoformat(timespec='minutes') if c['hour'] is not None else None
    candidates.sort(key=lambda c:(-c['score'],c['distance_km'],c['hour'] or 0,c['poi']['name']))
    limit = max(1,min(200,int(payload.get('limit',30))))
    return dict(results=candidates[:limit],total=len(candidates),meta=dict(service_date=day,boarding_station=board,quiet_weight=weight,weather_source=weather_sources,model_updated_at=datetime.fromtimestamp(MODEL_PATH.stat().st_mtime).isoformat(),distance_basis='출발 위치에서 장소까지 직선거리',load_basis='승차 후부터 하차 전까지 구간별 예상 재차인원 평균',limitations=['장소 자체의 방문객 혼잡도를 예측하지 않습니다.','운영시간 자료가 없어 장소 개방 여부는 확인되지 않았습니다.','같은 역 주변 장소는 열차 이동이 없어 한산함 점수를 중립값으로 표시합니다.','시간별 순위는 해당 시간대에 운행하는 열차 중 예상 구간 평균이 가장 낮은 열차 기준입니다.']))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def send_json(self, value, status=200):
        data=json.dumps(value,ensure_ascii=False,allow_nan=False).encode('utf-8')
        self.send_response(status)
        if self.headers.get('Origin') in ('http://127.0.0.1:5500','http://localhost:5500'):
            self.send_header('Access-Control-Allow-Origin',self.headers['Origin'])
            self.send_header('Vary','Origin')
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        if self.headers.get('Origin') in ('http://127.0.0.1:5500','http://localhost:5500'):
            self.send_header('Access-Control-Allow-Origin',self.headers['Origin'])
        self.send_header('Access-Control-Allow-Methods','GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers','Content-Type')
        self.end_headers()

    def do_GET(self):
        path=urlparse(self.path)
        try:
            if path.path == '/api/health':
                get_model()
                return self.send_json(dict(ok=True,model='load_predictor.joblib'))
            if path.path == '/api/stations':
                return self.send_json(dict(stations=stations()))
            if path.path == '/api/predict':
                q=parse_qs(path.query)
                service_date,hour=service_time(q['date'][0],int(q['hour'][0]))
                station=q['station'][0]
                direction=q.get('direction',['하행'])[0]
                if station not in STATION_NAMES or direction not in ('상행','하행'):
                    raise ValueError('역 또는 방향이 올바르지 않습니다.')
                weather,sources=weather_profile(service_date,[hour])
                features=[[STATION_NAMES.index(station),hour,0 if direction=='상행' else 1,int(holiday(service_date)),*weather[hour],int(service_date>=CHANGE)]]
                value=max(0,float(get_model().predict(pd.DataFrame(features,columns=FEATURES))[0]))
                return self.send_json(dict(service_date=service_date,hour=hour,station=station,direction=direction,predicted_load=round(value,1),weather_source=sources))
            self.send_json(dict(error='없는 API 경로입니다.'),404)
        except (ValueError,KeyError,TypeError) as exc:
            self.send_json(dict(error=str(exc)),400)
        except Exception:
            self.send_json(dict(error='모델 또는 데이터 파일을 읽지 못했습니다.'),503)

    def do_POST(self):
        if urlparse(self.path).path != '/api/recommend':
            return self.send_json(dict(error='없는 API 경로입니다.'),404)
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0 < length <= 100000:
                raise ValueError('요청 크기가 올바르지 않습니다.')
            result=recommend(json.loads(self.rfile.read(length)))
            self.send_json(result)
        except (ValueError,KeyError,TypeError) as exc:
            self.send_json(dict(error=str(exc)),400)
        except Exception:
            self.send_json(dict(error='예측 처리에 실패했습니다. 모델과 데이터 파일을 확인해 주세요.'),503)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8000)
    args=parser.parse_args()
    stations()
    get_model()
    print(f'Prediction API: http://127.0.0.1:{args.port}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
