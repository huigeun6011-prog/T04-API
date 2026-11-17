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
from urllib.parse import parse_qs, unquote, urlparse
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
# 도보 시간 추정: 직선거리 x 우회계수 / 보행속도. 실제 경로가 아닌 추정치다(D-014).
WALK_KMH = 4.5
WALK_DETOUR = 1.3
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
    max_walk = payload.get('max_walk_minutes')
    if max_walk is not None:
        max_walk = float(max_walk)
        if not 1 <= max_walk <= 240:
            raise ValueError('최대 도보 시간은 1~240분이어야 합니다.')
    for poi in pois:
        if not poi.get('has_coordinates') or (category != 'all' and poi['facility_type'] != category):
            continue
        point = dict(lat=float(poi['latitude']),lng=float(poi['longitude']))
        alight = nearest(point)
        base = dict(poi=poi, boarding_station=board, alighting_station=alight, distance_km=round(km(origin,point),3), walking_distance_km=round(km(origin,board)+km(point,alight),3), opening_hours=None)
        if alight['idx'] == board['idx']:
            walk_minutes = round(base['distance_km']*WALK_DETOUR/WALK_KMH*60)
            if max_walk is not None and walk_minutes > max_walk:
                continue
            base['walk_minutes'] = walk_minutes
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
    # 장소별로 묶어 가장 점수가 높은 후보만 결과로 두고, 같은 장소의 다른 선택지는 alt_times(최대 3개)로 붙인다.
    # 점수·정규화는 위에서 전체 후보 기준으로 이미 계산했으므로 바뀌지 않는다. limit 은 묶은 뒤(장소 수)에 적용한다.
    grouped = {}
    for c in candidates:
        poi = c['poi']
        key = poi.get('id') if poi.get('id') not in (None, '') else (poi.get('name'), poi.get('address'))
        grouped.setdefault(key, []).append(c)
    places = []
    place_keys = []
    place_walk_only = []
    for key, options in grouped.items():
        place_keys.append(key)
        best = dict(options[0])
        place_walk_only.append(bool(best['no_train']))
        best['alt_times'] = [dict(departure_time=o['departure_time'],arrival_time=o['arrival_time'],boarding_station=o['boarding_station']['name'],alighting_station=o['alighting_station']['name'],mean_load=o['mean_load'],score=o['score']) for o in options[1:4] if not o['no_train']]
        places.append(best)
    # 도보 전용 후보가 목록을 채우지 않도록 limit 의 1/3 까지만 먼저 담고, 자리가 남으면 나머지 도보 후보로 채운다(원래 순위 유지).
    walk_cap = max(1, limit // 3)
    chosen, skipped = [], []
    for i in range(len(places)):
        if len(chosen) >= limit:
            break
        if place_walk_only[i] and sum(place_walk_only[j] for j in chosen) >= walk_cap:
            skipped.append(i)
        else:
            chosen.append(i)
    chosen = sorted(chosen + skipped[:max(0, limit - len(chosen))])
    matrix = None
    if payload.get('include_matrix') is True:
        # 상위 장소(최대 15곳)의 시간대별 최선 후보를 이미 계산된 후보에서 그대로 꺼낸다(점수·정렬은 그대로).
        rows = []
        for key, best in [(place_keys[i], places[i]) for i in chosen][:min(limit, 15)]:
            by_hour = {}
            for c in grouped[key]:
                if c['hour'] is not None:
                    by_hour.setdefault(c['hour'], c)  # grouped 는 점수 내림차순이므로 첫 항목이 그 시간의 최선
            cells = [dict(hour=h, departure_time=by_hour[h]['departure_time'], mean_load=by_hour[h]['mean_load'], score=by_hour[h]['score']) if h in by_hour else dict(hour=h, departure_time=None, mean_load=None, score=None) for h in range(start, end+1)]
            rows.append(dict(poi_id=best['poi'].get('id'), name=best['poi'].get('name'), no_train=best['no_train'], cells=cells))
        matrix = dict(hours=list(range(start, end+1)), rows=rows)
    response = dict(results=[places[i] for i in chosen],total=len(candidates),place_total=len(places),meta=dict(service_date=day,boarding_station=board,quiet_weight=weight,weather_source=weather_sources,model_updated_at=datetime.fromtimestamp(MODEL_PATH.stat().st_mtime).isoformat(),distance_basis='출발 위치에서 장소까지 직선거리',load_basis='승차 후부터 하차 전까지 구간별 예상 재차인원 평균',limitations=['장소 자체의 방문객 혼잡도를 예측하지 않습니다.','운영시간 자료가 없어 장소 개방 여부는 확인되지 않았습니다.','같은 역 주변 장소는 열차 이동이 없어 한산함 점수를 중립값으로 표시합니다.','시간별 순위는 해당 시간대에 운행하는 열차 중 예상 구간 평균이 가장 낮은 열차 기준입니다.']))
    if matrix is not None:
        response['matrix'] = matrix
    response['meta']['max_walk_minutes'] = max_walk
    response['meta']['walk_basis'] = f'도보 시간은 직선거리 x {WALK_DETOUR} / {WALK_KMH}km/h 추정이며 실제 길이 아닙니다.'
    return response


@lru_cache(maxsize=32)
def _profile_cached(day, boarding, alighting):
    names = list(STATION_NAMES)
    trains, loads, sources = predict_profile(day, range(5, 25), boarding)
    by_hour = {h: [] for h in range(5, 25)}
    for train in trains:
        stops = train['stops']
        stop_names = [x['station'] for x in stops]
        if alighting not in stop_names or stop_names.index(boarding) >= stop_names.index(alighting):
            continue
        i, j = stop_names.index(boarding), stop_names.index(alighting)
        segment = []
        for stop in stops[i:j]:
            sh = int(stop['time'].split(':')[0]) or 24
            segment.append(loads[(stop['station'], sh, train['direction'])])
        hour = int(stops[i]['time'].split(':')[0]) or 24
        if 5 <= hour <= 24:
            by_hour[hour].append(dict(departure_time=stops[i]['time'], arrival_time=stops[j]['time'], direction=train['direction'], train_id=train['train_id'], mean_load=round(sum(segment)/len(segment), 1), max_load=round(max(segment), 1)))
    hours = []
    for h in range(5, 25):
        rows = sorted(by_hour[h], key=lambda t: t['departure_time'])
        means = sorted(t['mean_load'] for t in rows)
        n = len(means)
        median = None if not n else round(means[n//2] if n % 2 else (means[n//2-1] + means[n//2]) / 2, 1)
        hours.append(dict(hour=h, count=n, min=means[0] if n else None, median=median, max=means[-1] if n else None, trains=rows))
    return dict(service_date=day, boarding=boarding, alighting=alighting, holiday=holiday(day), weather_source=sources, hours=hours)


def profile(query):
    day = date.fromisoformat(query['date'][0]).isoformat()
    boarding, alighting = query['boarding'][0], query['alighting'][0]
    if boarding not in STATION_NAMES or alighting not in STATION_NAMES or boarding == alighting:
        raise ValueError('승차·하차 역이 올바르지 않습니다.')
    return _profile_cached(day, boarding, alighting)


WEB_ROOT = (ROOT / 'web').resolve()
STATIC_TYPES = {
    '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8',
    '.svg': 'image/svg+xml', '.png': 'image/png', '.ico': 'image/x-icon',
    '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.txt': 'text/plain; charset=utf-8',
}


def warm_up():
    """서버 시작 직후 백그라운드에서 첫 호출이 느려지는 원인(날씨 조회, 시간표·모델 초기화)을 미리 처리한다."""
    try:
        today = datetime.now().date()
        for version in ('20250930', '20260330'):
            schedule_file(version)
        model = get_model()
        model.predict(pd.DataFrame([[0, 8, 0, 0, 10.0, 0.0, 0.0, 1]], columns=FEATURES))
        for offset in (0, 1):  # 24시 구간은 다음 날 0시 날씨를 쓰므로 오늘과 내일을 모두 받아 둔다
            weather_day((today + timedelta(days=offset)).isoformat())
    except Exception:
        pass  # 준비 실패는 첫 요청이 같은 일을 다시 하며 오류를 보고한다


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

    def send_static(self, url_path, head=False):
        # 정적 파일은 web/ 아래에서만 제공한다. 경로를 resolve 해 심볼릭 링크/.. 우회를 막는다.
        if url_path in ('/', '/web', '/web/'):
            url_path = '/web/index.html'
        if not url_path.startswith('/web/'):
            return self.send_json(dict(error='없는 경로입니다.'),404)
        try:
            rel = unquote(url_path[len('/web/'):])
            if '\x00' in rel:
                raise ValueError
            target = (WEB_ROOT / rel).resolve()
            target.relative_to(WEB_ROOT)
            if not target.is_file():
                raise FileNotFoundError
            data = target.read_bytes()
        except (ValueError, OSError):
            return self.send_json(dict(error='없는 경로입니다.'),404)
        self.send_response(200)
        self.send_header('Content-Type',STATIC_TYPES.get(target.suffix.lower(),'application/octet-stream'))
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-cache')
        self.send_header('X-Content-Type-Options','nosniff')
        self.end_headers()
        if not head:
            self.wfile.write(data)

    def do_HEAD(self):
        path=urlparse(self.path)
        if path.path.startswith('/api/'):
            return self.send_json(dict(error='HEAD는 지원하지 않습니다.'),405)
        self.send_static(path.path,head=True)

    def do_GET(self):
        path=urlparse(self.path)
        if not path.path.startswith('/api/'):
            return self.send_static(path.path)
        try:
            if path.path == '/api/health':
                get_model()
                return self.send_json(dict(ok=True,model='load_predictor.joblib'))
            if path.path == '/api/stations':
                return self.send_json(dict(stations=stations()))
            if path.path == '/api/profile':
                return self.send_json(profile(parse_qs(path.query)))
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
    parser.add_argument('--port',type=int,default=5500)
    args=parser.parse_args()
    stations()
    get_model()
    threading.Thread(target=warm_up, daemon=True).start()
    print(f'Prediction API: http://127.0.0.1:{args.port}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
