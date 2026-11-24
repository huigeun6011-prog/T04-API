/* Browser inference and recommendation port. No server or model libraries required. */
(function (root) {
  'use strict';
  const cmp = (a, b) => a < b ? -1 : a > b ? 1 : 0;
  const abortError = () => Object.assign(new Error('요청을 취소했습니다.'), {name: 'AbortError'});
  function check(signal) { if (signal?.aborted) throw abortError(); }
  function subscribed(promise, signal) {
    check(signal);
    if (!signal) return promise;
    return new Promise((resolve, reject) => {
      const abort = () => { cleanup(); reject(abortError()); };
      const cleanup = () => signal.removeEventListener('abort', abort);
      signal.addEventListener('abort', abort, {once: true});
      promise.then(v => { cleanup(); signal.aborted ? reject(abortError()) : resolve(v); }, e => { cleanup(); reject(e); });
    });
  }
  // Round the exact binary double to decimal with ties to even, as Python does.
  function round(value, digits = 0) {
    if (!Number.isFinite(value) || value === 0) return value;
    const buf = new DataView(new ArrayBuffer(8)); buf.setFloat64(0, Math.abs(value));
    const bits = buf.getBigUint64(0), exp = Number((bits >> 52n) & 2047n);
    let numerator = (bits & ((1n << 52n) - 1n)) | (exp ? 1n << 52n : 0n);
    const power = (exp ? exp - 1023 : -1022) - 52;
    let denominator = 1n;
    if (power >= 0) numerator <<= BigInt(power); else denominator <<= BigInt(-power);
    if (digits >= 0) numerator *= 10n ** BigInt(digits); else denominator *= 10n ** BigInt(-digits);
    let q = numerator / denominator; const r = numerator % denominator;
    if (r * 2n > denominator || (r * 2n === denominator && q % 2n)) q++;
    return (value < 0 ? -1 : 1) * Number(q) / (10 ** digits);
  }
  function predict(model, input) {
    if (model.format !== 'hgb-squared-v1') throw new Error('지원하지 않는 모델입니다.');
    const x = model.input_order.map((original, i) => {
      const v = input[original];
      if (i < model.ordinal_categories.length) {
        const encoded = model.ordinal_categories[i].indexOf(v);
        return encoded < 0 ? NaN : encoded;
      }
      return v === null ? NaN : v;
    });
    let value = model.base;
    for (const tree of model.trees) {
      let n = tree.nodes[0];
      while (!n[6]) {
        const v = x[n[1]];
        let left;
        if (Number.isNaN(v)) left = !!n[3];
        else if (n[7]) left = !!((tree.categories[n[8]][v >>> 5] >>> (v & 31)) & 1);
        else left = v <= (n[2] === 'Infinity' ? Infinity : n[2]);
        n = tree.nodes[left ? n[4] : n[5]];
      }
      value += n[0];
    }
    return value;
  }
  const addDays = (day, n) => new Date(Date.parse(day + 'T00:00:00Z') + n * 86400000).toISOString().slice(0, 10);
  function validDate(day) {
    if (typeof day !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(day) || !Number.isFinite(Date.parse(day + 'T00:00:00Z')) || addDays(day, 0) !== day) throw new Error('날짜 형식이 올바르지 않습니다.');
    return day;
  }
  function createEngine(options = {}) {
    const base = options.baseURL || root.document?.baseURI || 'http://localhost/';
    const fetcher = options.fetch || root.fetch?.bind(root);
    const resources = options.resources || {};
    let ready;
    const cache = new Map(), pending = new Map();
    const successfulForecasts = new Map();
    const daily = options.dailyWeather || root.DailyWeather || (typeof require === 'function' ? require('./weather-daily.js') : undefined);
    const weatherFields = ['temperature_2m', 'precipitation', 'snowfall'];
    function complete(hourly, day) {
      return Array.isArray(hourly?.time) && hourly.time.length === 24 &&
        hourly.time.every((t, i) => t === `${day}T${String(i).padStart(2, '0')}:00`) &&
        weatherFields.every(k => Array.isArray(hourly[k]) && hourly[k].length === 24 &&
          hourly[k].every(v => Number.isFinite(v) && (k === 'temperature_2m' || v >= 0)));
    }
    async function fallbackWeather(day, failure) {
      const candidates = [];
      const saved = cache.get(day)?.value;
      if (saved) candidates.push(saved);
      const forecasts = [...successfulForecasts.values()].sort((a,b) => cmp(b.fetched_at, a.fetched_at));
      const shared = (options.getLastSuccessfulForecast || daily?.getLastSuccessfulForecast)?.();
      function fromRecord(record, kind) {
        const r = daily.validateRecord(record);
        if (daily.kindOf(r) !== kind || !/^https:\/\/(?:api|archive-api)\.open-meteo\.com\//.test(r.reading.source_url)) return;
        return {date: daily.dataDateOf(r), hourly: r.raw.hourly, source: kind,
          fetched_at: r.reading.fetched_at, source_url: r.reading.source_url};
      }
      let sharedWeather;
      try { if (shared) sharedWeather = fromRecord(shared, 'forecast'); } catch (_) { /* Invalid or synthetic records are ineligible. */ }
      if (sharedWeather?.date === day) candidates.push(sharedWeather);
      candidates.push(...[...forecasts, ...(sharedWeather ? [sharedWeather] : [])].sort((a,b) => cmp(b.fetched_at, a.fetched_at)));
      let chosen = candidates.find(w => complete(w.hourly, w.date));
      if (!chosen && daily) {
        try {
          const doc = options.fallbackRows ? await options.fallbackRows() : await json(daily.recordPath);
          const rows = daily.readRows(Array.isArray(doc) ? {rows: doc} : doc);
          chosen = rows.map(r => fromRecord(r, 'observed')).filter(Boolean)
            .sort((a,b) => cmp(b.date, a.date) || cmp(b.fetched_at, a.fetched_at))[0];
        } catch (_) { /* No usable stored observation: preserve the original failure. */ }
      }
      if (!chosen) return failure;
      const provenance = {requested_date: day, source_date: chosen.date, fetched_at: chosen.fetched_at,
        source_url: chosen.source_url || new URL(`data/weather/${chosen.date}.json`, base).href,
        kind: ['archive', 'local_archive'].includes(chosen.source) ? 'observed' : chosen.source,
        reason: failure.reason, error_kind: failure.error_kind};
      return {available: true, date: day, source: 'fallback', cached: false, fetched_at: chosen.fetched_at,
        source_url: provenance.source_url, source_date: chosen.date, fallback: provenance,
        hourly: {...chosen.hourly, time: chosen.hourly.time.map(t => day + t.slice(10))}};
    }
    let queue = Promise.resolve(), lastRemote = 0;
    async function json(path) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), options.timeoutMs ?? 25000);
      try {
        const response = await fetcher(new URL(path, base).href, {signal: controller.signal});
        if (!response.ok) throw Object.assign(new Error('자료를 불러오지 못했습니다.'), {status: response.status});
        return await response.json();
      } finally { clearTimeout(timer); }
    }
    function preload() {
      if (!ready) ready = Promise.all([resources.model || json('data/model.json'), resources.runtime || json('data/runtime.json')]).catch(e => { ready = null; throw e; });
      return ready;
    }
    function today() { return new Date((options.now ? options.now() : Date.now()) + 9 * 3600000).toISOString().slice(0, 10); }
    async function loadWeather(day) {
      if (options.weather) {
        const w = await options.weather(day);
        return w.available !== undefined ? w : {available: true, date: day, source: 'local_archive', cached: false, fetched_at: new Date().toISOString(), hourly: w.hourly || w};
      }
      try {
        const local = await json(`data/weather/${day}.json`);
        return {available: true, date: day, source: 'local_archive', cached: false, fetched_at: new Date().toISOString(), hourly: local.hourly};
      } catch (_) { /* A missing archive falls through to the public weather service. */ }
      if (day > addDays(today(), 15)) throw new Error('예보는 오늘부터 15일 후까지 제공됩니다.');
      const task = queue.then(async () => {
        const wait = Math.max(0, (options.minRequestIntervalMs ?? 10000) - (Date.now() - lastRemote));
        if (wait) await new Promise(resolve => setTimeout(resolve, wait));
        const source = day < today() ? 'archive' : 'forecast';
        const endpoint = source === 'archive' ? 'https://archive-api.open-meteo.com/v1/archive' : 'https://api.open-meteo.com/v1/forecast';
        const params = new URLSearchParams({latitude: '36.35', longitude: '127.38', hourly: 'temperature_2m,precipitation,snowfall', timezone: 'Asia/Seoul', start_date: day, end_date: day});
        lastRemote = Date.now();
        const data = await json(`${endpoint}?${params}`), raw = data.hourly;
        const indices = raw.time.map((t, i) => t.startsWith(day + 'T') ? i : -1).filter(i => i >= 0);
        if (indices.length !== 24) throw new Error('선택한 날짜의 시간별 날씨가 없습니다.');
        const hourly = Object.fromEntries(['time', 'temperature_2m', 'precipitation', 'snowfall'].map(k => [k, indices.map(i => raw[k][i])]));
        return {available: true, date: day, source, cached: false, fetched_at: new Date().toISOString(), source_url: `${endpoint}?${params}`, hourly};
      });
      queue = task.catch(() => {});
      return task;
    }
    // 표시용 분류만 한다(추천 계산에는 쓰이지 않음): timeout / auth / rate_limit / offline / schema_error.
    function weatherErrorKind(e) {
      const status = e && e.status;
      if (status === 401 || status === 403) return 'auth';
      if (status === 429) return 'rate_limit';
      if (status === 408 || status === 504) return 'timeout';
      if (typeof status === 'number') return status >= 500 ? 'offline' : 'schema_error';
      if (e && (e.name === 'AbortError' || e.name === 'TimeoutError')) return 'timeout';
      if (e instanceof TypeError) return 'offline';
      return 'schema_error';
    }
    async function fetchWeatherForDate(day, {signal} = {}) {
      check(signal);
      try { validDate(day); } catch (e) { return {available: false, date: day, reason: e.message}; }
      const saved = cache.get(day);
      if (saved && Date.now() < saved.expires) return subscribed(Promise.resolve({...saved.value, cached: true}), signal);
      if (!pending.has(day)) {
        pending.set(day, loadWeather(day).then(value => {
          if (!value.available) return fallbackWeather(day, value);
          if (!complete(value.hourly, day)) return fallbackWeather(day, {available: false, date: day, reason: '시간별 날씨가 불완전합니다.', error_kind: 'schema_error'});
          cache.set(day, {value, expires: Date.now() + (options.cacheTtlMs ?? (value.source === 'local_archive' ? Infinity : day < today() ? 7 * 86400000 : 3600000))});
          if (value.source === 'forecast') successfulForecasts.set(day, value);
          return value;
        }).catch(e => fallbackWeather(day, {available: false, date: day, reason: e.message, error_kind: weatherErrorKind(e)})).finally(() => pending.delete(day)));
      }
      return subscribed(pending.get(day), signal);
    }
    function km(a, b) {
      const rad = v => v * Math.PI / 180;
      const [lat1, lon1, lat2, lon2] = [a.lat, a.lng, b.lat, b.lng].map(rad);
      const h = Math.sin((lat2-lat1)/2)**2 + Math.cos(lat1)*Math.cos(lat2)*Math.sin((lon2-lon1)/2)**2;
      return 6371 * 2 * Math.asin(Math.min(1, Math.sqrt(h)));
    }
    async function recommend(payload, {signal} = {}) {
      check(signal);
      const [model, rt] = await subscribed(preload(), signal);
      const day = validDate(String(payload.date));
      const integer = v => { const n = Number(v); if (!Number.isFinite(n) || (typeof v === 'string' && !/^[+-]?\d+$/.test(v.trim()))) throw new Error('시간은 정수여야 합니다.'); return Math.trunc(n); };
      const start = integer(payload.start_hour ?? 5), end = integer(payload.end_hour ?? 24);
      if (!(5 <= start && start <= end && end <= 24)) throw new Error('시작·종료 시간은 05~24시여야 합니다.');
      const origin = {lat: Number(payload.origin.lat), lng: Number(payload.origin.lng)};
      if (!Number.isFinite(origin.lat) || !Number.isFinite(origin.lng) || Math.abs(origin.lat) > 90 || Math.abs(origin.lng) > 180) throw new Error('출발 좌표가 올바르지 않습니다.');
      const nearest = point => rt.stations.reduce((best, s) => km(point, s) < km(point, best) ? s : best);
      const board = nearest(origin), weekday = new Date(day + 'T00:00:00Z').getUTCDay();
      const holiday = weekday === 0 || weekday === 6 || rt.holidays.includes(day);
      const version = day >= rt.change && !holiday ? '20260330' : '20250930';
      const hour = stop => Number(stop.time.split(':')[0]) || 24;
      const trains = rt.schedules[version].filter(t => t.day_type === (holiday ? '휴일' : '평일') && t.stops.slice(0, -1).some(s => s.station === board.name && start <= hour(s) && hour(s) <= end));
      const hours = [...new Set(trains.flatMap(t => t.stops.map(hour)))].filter(h => 5 <= h && h <= 24).sort((a,b) => a-b);
      const weather = new Map(), sources = new Set(), fallbacks = new Map(), requestWeather = new Map();
      for (const h of hours) {
        const d = h === 24 ? addDays(day, 1) : day;
        if (!requestWeather.has(d)) requestWeather.set(d, await fetchWeatherForDate(d, {signal}));
        const w = requestWeather.get(d); check(signal);
        if (w.fallback) fallbacks.set(d, w.fallback);
        if (!w.available) throw new Error(w.reason);
        const i = w.hourly.time.indexOf(`${d}T${String(h % 24).padStart(2, '0')}:00`);
        const values = ['temperature_2m', 'precipitation', 'snowfall'].map(k => w.hourly[k]?.[i]);
        if (i < 0 || !values.every(v => typeof v === 'number' && Number.isFinite(v))) throw new Error('해당 시간의 날씨 자료가 없습니다.');
        weather.set(h, values); sources.add(w.source);
      }
      const loads = new Map(), key = (name,h,dir) => JSON.stringify([name,h,dir]);
      for (const t of trains) for (const s of t.stops.slice(0, -1)) {
        const h = hour(s), k = key(s.station,h,t.direction);
        if (!weather.has(h) || loads.has(k)) continue;
        loads.set(k, Math.max(0, predict(model, [rt.station_names.indexOf(s.station),h,t.direction === '상행' ? 0 : 1,Number(holiday),...weather.get(h),Number(day >= rt.change)])));
      }
      const pendingTrips = new Map(), minutes = s => { const [h,m] = s.split(':').map(Number); return h*60+m; };
      for (const t of trains) {
        const i = t.stops.findIndex(s => s.station === board.name), departure = t.stops[i].time, h = hour(t.stops[i]);
        for (let j = i+1; j < t.stops.length; j++) {
          const name = t.stops[j].station, k = key(name,h,'');
          const segment = t.stops.slice(i,j).map(s => loads.get(key(s.station,hour(s),t.direction)));
          if (!pendingTrips.has(k)) pendingTrips.set(k, {name,h,rows: []});
          pendingTrips.get(k).rows.push({load: segment.reduce((a,b)=>a+b,0)/segment.length, ride: ((minutes(t.stops[j].time)-minutes(departure))%1440+1440)%1440, train: {departure_time: departure, arrival_time: t.stops[j].time}, direction: t.direction});
        }
      }
      const routes = new Map();
      for (const {name,h,rows} of pendingTrips.values()) {
        if (!routes.has(name)) routes.set(name, []);
        routes.get(name).push({hour:h, mean:round(rows.reduce((a,r)=>a+r.load,0)/rows.length,1), ride:round(rows.reduce((a,r)=>a+r.ride,0)/rows.length), direction:rows[0].direction, trains:rows.map(r=>r.train).sort((a,b)=>cmp(a.departure_time,b.departure_time))});
      }
      for (const [name, rows] of routes) {
        const sorted = [...rows].sort((a,b)=>a.mean-b.mean || a.hour-b.hour);
        rows.sort((a,b)=>a.hour-b.hour);
        routes.set(name, {hour_ranks:rows.map(r=>({hour:r.hour,rank:sorted.indexOf(r)+1,trains:r.trains})), rank_n:rows.length, ride:round(rows.reduce((a,r)=>a+r.ride,0)/rows.length), direction:rows[0].direction});
      }
      const limit = v => {
        if (v === undefined || v === null || v === '') return null;
        if (typeof v === 'boolean' || !['string','number'].includes(typeof v) || !String(v).trim()) throw new Error('이동 구간은 정수여야 합니다.');
        const n = Number(v); if (!Number.isInteger(n) || n < 1 || n >= rt.stations.length) throw new Error('이동 구간은 1~21 사이 정수여야 합니다.'); return n;
      };
      const minStops = limit(payload.min_stops), maxStops = limit(payload.max_stops);
      if (minStops !== null && maxStops !== null && minStops > maxStops) throw new Error('구간 범위가 올바르지 않습니다.');
      const maxWalk = payload.max_walk_minutes == null ? null : Number(payload.max_walk_minutes);
      if (maxWalk !== null && !(1 <= maxWalk && maxWalk <= 240)) throw new Error('최대 도보 시간은 1~240분이어야 합니다.');
      const members = new Map(), push = (name,p) => { if (!members.has(name)) members.set(name,[]); members.get(name).push(p); };
      for (const poi of rt.pois) {
        if (!poi.has_coordinates || ((payload.category ?? 'all') !== 'all' && poi.facility_type !== payload.category)) continue;
        const point = {lat:Number(poi.latitude),lng:Number(poi.longitude)}, alight = nearest(point);
        const direct = km(origin,point), directWalk = round(direct*rt.walk_min_per_km), stops = Math.abs(alight.idx-board.idx);
        const place = {poi,distance_km:round(direct,3)}, directAllowed = maxWalk === null || directWalk <= maxWalk;
        const walk = {...place,walking_distance_km:round(direct,3),walk_access_minutes:directWalk,walk_egress_minutes:0,walk_total_minutes:directWalk};
        if (stops === 0) { if (minStops === null && directAllowed) push(null,walk); continue; }
        if ((minStops !== null && stops < minStops) || (maxStops !== null && stops > maxStops)) continue;
        const route = routes.get(alight.name), access = round(km(origin,board)*rt.walk_min_per_km), egress = round(km(point,alight)*rt.walk_min_per_km);
        const transit = !!route && (maxWalk === null || access+egress <= maxWalk);
        if (minStops === null && directAllowed && (!transit || access+egress+route.ride > directWalk)) push(null,walk);
        else if (transit) push(alight.name,{...place,walking_distance_km:round(km(origin,board)+km(point,alight),3),walk_access_minutes:access,walk_egress_minutes:egress,walk_total_minutes:access+egress});
      }
      const groups = [], order = {library:0,park:1,bookstore:2};
      for (const [name,places] of members) {
        const cats = new Map();
        places.sort((a,b)=>a.distance_km-b.distance_km || cmp(a.poi.name || '',b.poi.name || ''));
        for (const p of places) { const c=p.poi.facility_type; if (!cats.has(c)) cats.set(c,[]); cats.get(c).push(p); }
        const group = {kind:name === null ? 'walk':'route',categories:[...cats.keys()].sort((a,b)=>(order[a]??9)-(order[b]??9)||cmp(String(a),String(b))).map(c=>({category:c,places:cats.get(c)})),nearest_km:Math.min(...places.map(p=>p.distance_km))};
        if (name === null) group.id='walk';
        else { const a=rt.stations.find(s=>s.name===name), r=routes.get(name); Object.assign(group,{id:`${board.name}->${name}`,boarding_station:board,alighting_station:a,stops:Math.abs(a.idx-board.idx),direction:r.direction,rank_n:r.rank_n,hour_ranks:r.hour_ranks}); }
        groups.push(group);
      }
      groups.sort((a,b)=>a.nearest_km-b.nearest_km || cmp(a.id,b.id)); check(signal);
      return {groups,meta:{...rt.meta,service_date:day,boarding_station:board,weather_source:[...sources].sort(cmp),min_stops:minStops,max_stops:maxStops,max_walk_minutes:maxWalk,
        ...(fallbacks.size ? {weather_fallbacks: [...fallbacks.values()]} : {})}};
    }
    return Object.freeze({recommend,fetchWeatherForDate,preload});
  }
  const api = {...createEngine(),createEngine,predict,round};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.StaticRecommendation = api;
})(typeof globalThis !== 'undefined' ? globalThis : window);
