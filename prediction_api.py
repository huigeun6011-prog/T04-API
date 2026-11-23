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
WALK_MIN_PER_KM = WALK_DETOUR / WALK_KMH * 60
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


def clock_minutes(text):
    h, m = str(text).split(':')[:2]
    return int(h) * 60 + int(m)       # 24시 이후 표기(24:05 등)도 그대로 분으로 환산


def plain_ranks(loads):
    """hour -> 예상 재차 로 같은 구간 안의 시간대 순위(정수 1..N, 1 = 가장 한산). 값이 정확히 같으면 이른 시간이 앞선다. 수치는 밖으로 내보내지 않는다(D-028).
    순위 차이 2 이하를 같은 수준으로 보는 규칙은 두 시간대를 비교할 때만 쓰며(화면), 여기서는 묶지 않는다."""
    return {h: r for r, h in enumerate(sorted(loads, key=lambda k: (loads[k], k)), 1)}


def stop_limit(value, label):
    """지하철 이동 구간 수(역과 역 사이 한 칸 = 1) 한도. 비어 있으면 제한 없음."""
    if value is None or value == '':
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f'지하철 이동 구간({label})은 정수여야 합니다.')
    try:
        number = float(value)
    except ValueError:
        raise ValueError(f'지하철 이동 구간({label})은 정수여야 합니다.') from None
    if not number.is_integer() or not 1 <= number <= len(stations()) - 1:
        raise ValueError(f'지하철 이동 구간({label})은 1~{len(stations()) - 1} 사이의 정수여야 합니다.')
    return int(number)


def recommend(payload):
    day = date.fromisoformat(str(payload['date'])).isoformat()
    start, end = int(payload.get('start_hour', 5)), int(payload.get('end_hour', 24))
    if not (5 <= start <= end <= 24):
        raise ValueError('시작·종료 시간은 05~24시이며 시작은 종료보다 늦을 수 없습니다.')
    origin = {k: float(payload['origin'][k]) for k in ('lat','lng')}
    if not all(math.isfinite(v) for v in origin.values()) or not (-90 <= origin['lat'] <= 90 and -180 <= origin['lng'] <= 180):
        raise ValueError('출발 좌표가 올바르지 않습니다.')
    board = nearest(origin)
    trains, loads, weather_sources = predict_profile(day, range(start, end+1), board['name'])
    pois = json.loads((ROOT/'web/data/pois.json').read_text(encoding='utf-8'))
    # 승차역 출발 열차를 (하차역, 시간)별로 모은다. 한 열차만 고르지 않고 시간대 값은 그 열차들의 평균이다(D-028).
    pending = {}
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
            ride = clock_minutes(stops[j]['time']) - clock_minutes(departure)
            pending.setdefault((names[j], hour), []).append((sum(segment)/len(segment), ride % 1440, dict(departure_time=departure, arrival_time=stops[j]['time']), train['direction']))
    trips, route_ranks = {}, {}
    for (name, hour), rows in pending.items():
        trips[(name, hour)] = dict(hour=hour, direction=rows[0][3], trains=sorted((r[2] for r in rows), key=lambda t: t['departure_time']), mean_load=round(sum(r[0] for r in rows)/len(rows),1), ride_minutes=round(sum(r[1] for r in rows)/len(rows)), no_train=False)
        route_ranks.setdefault(name, {})[hour] = trips[(name, hour)]['mean_load']
    # 순위는 고른 시간 범위 전체에서 먼저 매기고, 그 뒤에 도보·구간 수 필터를 적용한다. 그래서 필터가 순위를 바꾸지 않는다.
    route_ranks = {name: plain_ranks(v) for name, v in route_ranks.items()}
    category = payload.get('category','all')
    max_walk = payload.get('max_walk_minutes')
    if max_walk is not None:
        max_walk = float(max_walk)
        if not 1 <= max_walk <= 240:
            raise ValueError('최대 도보 시간은 1~240분이어야 합니다.')
    min_stops, max_stops = stop_limit(payload.get('min_stops'), '이상'), stop_limit(payload.get('max_stops'), '이하')
    if min_stops is not None and max_stops is not None and min_stops > max_stops:
        raise ValueError('지하철 이동 구간의 이상 값은 이하 값보다 클 수 없습니다.')
    # 경로(하차역) 단위 자료: 순위는 고른 시간 범위 전체에서 한 번 매기고 필터와 무관하다. 도보 대 열차 판단도 경로 단위(시간대 평균 소요)로 한다.
    routes = {}
    for name, ranks in route_ranks.items():
        hours = sorted(ranks)
        routes[name] = dict(hour_ranks=[dict(hour=h, rank=ranks[h], trains=trips[(name, h)]['trains']) for h in hours], rank_n=len(hours),
                            ride=round(sum(trips[(name, h)]['ride_minutes'] for h in hours)/len(hours)), direction=trips[(name, hours[0])]['direction'])
    members = {}     # 묶음 키 -> 장소 목록. 키는 하차역 이름 또는 None(걸어서)
    for poi in pois:
        if not poi.get('has_coordinates') or (category != 'all' and poi['facility_type'] != category):
            continue
        point = dict(lat=float(poi['latitude']),lng=float(poi['longitude']))
        alight = nearest(point)
        direct_km = km(origin,point)
        direct_walk = round(direct_km * WALK_MIN_PER_KM)
        place = dict(poi=poi, distance_km=round(direct_km,3))
        stops = abs(alight['idx'] - board['idx'])
        direct_allowed = max_walk is None or direct_walk <= max_walk
        walk_place = dict(place, walking_distance_km=round(direct_km,3), walk_access_minutes=direct_walk, walk_egress_minutes=0, walk_total_minutes=direct_walk)
        if stops == 0:
            # 같은 역이면 열차 없이 걷는다(0구간). 이상(min_stops)을 정하면 제외된다.
            if min_stops is None and direct_allowed and (max_stops is None or 0 <= max_stops):
                members.setdefault(None, []).append(walk_place)
            continue
        if (min_stops is not None and stops < min_stops) or (max_stops is not None and stops > max_stops):
            continue                                   # 구간 수 조건을 벗어나는 경로의 장소는 걸어서 가는 후보로도 넣지 않는다
        route = routes.get(alight['name'])
        access = round(km(origin,board)*WALK_MIN_PER_KM)
        egress = round(km(point,alight)*WALK_MIN_PER_KM)
        transit_ok = route is not None and (max_walk is None or access + egress <= max_walk)
        # 이상(min_stops)을 정하면 걷는 편이 빨라도 열차 후보를 보여 준다. 정하지 않으면 걷는 편이 빠를 때(경로 평균 소요 기준) 걸어서 묶음으로 보낸다.
        walk_wins = min_stops is None and direct_allowed and (not transit_ok or access + egress + route['ride'] > direct_walk)
        if walk_wins:
            members.setdefault(None, []).append(walk_place)
        elif transit_ok:
            members.setdefault(alight['name'], []).append(dict(place, walking_distance_km=round(km(origin,board)+km(point,alight),3), walk_access_minutes=access, walk_egress_minutes=egress, walk_total_minutes=access+egress))
    order = {'library': 0, 'park': 1, 'bookstore': 2}
    groups = []
    for name, places in members.items():
        cats = {}
        for pl in sorted(places, key=lambda x: (x['distance_km'], x['poi'].get('name') or '')):
            cats.setdefault(pl['poi'].get('facility_type'), []).append(pl)
        group = dict(kind='walk' if name is None else 'route', categories=[dict(category=c, places=cats[c]) for c in sorted(cats, key=lambda c: (order.get(c, 9), str(c)))],
                     nearest_km=min(pl['distance_km'] for pl in places))
        if name is None:
            group.update(id='walk')
        else:
            alight = next(x for x in stations() if x['name'] == name)
            group.update(id=f"{board['name']}->{name}", boarding_station=board, alighting_station=alight, stops=abs(alight['idx'] - board['idx']), direction=routes[name]['direction'], rank_n=routes[name]['rank_n'], hour_ranks=routes[name]['hour_ranks'])
        groups.append(group)
    groups.sort(key=lambda g: (g['nearest_km'], g['id']))
    response = dict(groups=groups,
                    meta=dict(service_date=day,boarding_station=board,weather_source=weather_sources,model_updated_at=datetime.fromtimestamp(MODEL_PATH.stat().st_mtime).isoformat(),distance_basis='출발 위치에서 장소까지 직선거리',rank_basis='같은 승차역 -> 하차역, 같은 방향에서 사용자가 고른 시간 범위 안의 시간대끼리만 매긴 상대 순서(1 = 가장 한산). 인원 수는 보여 주지 않습니다.',tie_rule='순위는 정수 1..N이며 값이 같으면 이른 시간이 앞섭니다. 묶지 않고 그대로 보여 줍니다. 두 시간대를 비교할 때 순위 차이가 2 이하이면 실제 차이로 보지 않고, 3 이상이면 순위 숫자가 작은 쪽이 더 한산합니다.',limitations=['장소 자체의 방문객 혼잡도를 예측하지 않습니다.','운영시간 자료가 없어 장소 개방 여부는 확인되지 않았습니다.','시간대 순위는 그 시간대 열차들의 예상 평균으로 같은 구간의 시간대끼리만 비교한 것이며 열차 한 대의 순서가 아닙니다. 장소 사이 비교가 아닙니다.','순위는 피크 시간 사례에서만 검증되었습니다. 한산한 쪽 순서는 대전에서 검증되지 않았습니다.','이상 구간을 정하지 않으면 걷는 편이 더 빠를 때(구간 평균 소요 기준) 걸어서 묶음으로 보냅니다. 이상을 정하면 걸어서 가는 장소는 빠지고 열차 후보를 보여 줍니다.','걷는 시간은 직선거리 기반 추정이며 대기·환승 시간은 포함하지 않습니다.'],
                    min_stops=min_stops, max_stops=max_stops, max_walk_minutes=max_walk))
    response['meta']['walk_basis'] = f'걷는 시간은 직선거리 x {WALK_DETOUR} / {WALK_KMH}km/h 추정이며 실제 길이 아닙니다. 최대 도보 시간은 승차역까지와 하차역에서 걷는 시간의 합(걸어서 가면 곧바로 걷는 시간)에 적용됩니다.'
    return response


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
