/*
 * Open-Meteo weather client for the Daejeon demo.
 *
 * Usage from app.js (only when the selected date changes):
 *   const weather = await window.WeatherClient.fetchForDate(dateString);
 *
 * Success:
 *   { available: true, date, source, cached, hourly: {
 *       time, temperature_2m, precipitation, snowfall
 *   }}
 * Failure/unavailable:
 *   { available: false, date, reason }
 *
 * Forecast range: today through today + 15 days. Past dates use the
 * Open-Meteo archive endpoint. No API key is required.
 */
(function attachWeatherClient(root) {
  'use strict';

  const LATITUDE = 36.35;
  const LONGITUDE = 127.38;
  const CACHE_PREFIX = 'daejeon-open-meteo:v1:';
  const LAST_REQUEST_KEY = 'daejeon-open-meteo:last-request-at:v1';
  const FORECAST_TTL_MS = 60 * 60 * 1000;
  const ARCHIVE_TTL_MS = 7 * 24 * 60 * 60 * 1000;
  const DEBOUNCE_MS = 500;
  const MIN_REQUEST_INTERVAL_MS = 10 * 1000;
  const REQUEST_TIMEOUT_MS = 15 * 1000;

  const memoryCache = new Map();
  const inFlight = new Map();
  let pendingRequest = null;
  let dispatchTimer = null;

  function todayInSeoul() {
    const parts = new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Asia/Seoul',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).formatToParts(new Date());
    const values = Object.fromEntries(parts.map(part => [part.type, part.value]));
    return `${values.year}-${values.month}-${values.day}`;
  }

  function addDays(dateString, count) {
    const date = new Date(`${dateString}T00:00:00Z`);
    date.setUTCDate(date.getUTCDate() + count);
    return date.toISOString().slice(0, 10);
  }

  function isValidDateString(dateString) {
    if (typeof dateString !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(dateString)) return false;
    const date = new Date(`${dateString}T00:00:00Z`);
    return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === dateString;
  }

  function unavailable(date, reason) {
    return { available: false, date, reason };
  }

  function getStorage(key) {
    try { return root.localStorage.getItem(key); } catch (_) { return null; }
  }

  function setStorage(key, value) {
    try { root.localStorage.setItem(key, value); } catch (_) { /* storage may be disabled */ }
  }

  function readCached(date, now = Date.now()) {
    const fromMemory = memoryCache.get(date);
    if (fromMemory && now - fromMemory.cachedAt < fromMemory.ttl) {
      return { ...fromMemory.result, cached: true };
    }

    const raw = getStorage(`${CACHE_PREFIX}${date}`);
    if (!raw) return null;

    try {
      const cached = JSON.parse(raw);
      const ttl = cached.source === 'archive' ? ARCHIVE_TTL_MS : FORECAST_TTL_MS;
      if (!cached.result || now - cached.cachedAt >= ttl) return null;
      memoryCache.set(date, { ...cached, ttl });
      return { ...cached.result, cached: true };
    } catch (_) {
      return null;
    }
  }

  function writeCached(result) {
    const cachedAt = Date.now();
    const ttl = result.source === 'archive' ? ARCHIVE_TTL_MS : FORECAST_TTL_MS;
    const cached = { result, source: result.source, cachedAt, ttl };
    memoryCache.set(result.date, cached);
    setStorage(`${CACHE_PREFIX}${result.date}`, JSON.stringify(cached));
  }

  function lastRequestAt() {
    const value = Number(getStorage(LAST_REQUEST_KEY));
    return Number.isFinite(value) ? value : 0;
  }

  function settlePendingAsUnavailable(reason) {
    if (!pendingRequest) return;
    const previous = pendingRequest;
    pendingRequest = null;
    previous.resolve(unavailable(previous.date, reason));
  }

  function scheduleDispatch(delay = DEBOUNCE_MS) {
    if (dispatchTimer !== null) root.clearTimeout(dispatchTimer);
    dispatchTimer = root.setTimeout(dispatchPending, delay);
  }

  async function dispatchPending() {
    dispatchTimer = null;
    if (!pendingRequest) return;

    const waitMs = MIN_REQUEST_INTERVAL_MS - (Date.now() - lastRequestAt());
    if (waitMs > 0) {
      scheduleDispatch(waitMs);
      return;
    }

    const request = pendingRequest;
    pendingRequest = null;

    // Persist the throttle timestamp before starting the network request so
    // repeated page loads and other tabs observe the same request interval.
    setStorage(LAST_REQUEST_KEY, String(Date.now()));

    inFlight.set(request.date, request.promise);
    loadWeather(request.date)
      .then(request.resolve)
      .catch(() => request.resolve(unavailable(request.date, '날씨를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.')))
      .finally(() => {
        inFlight.delete(request.date);
        if (pendingRequest) scheduleDispatch(DEBOUNCE_MS);
      });
  }

  async function loadWeather(date) {
    const today = todayInSeoul();
    const source = date < today ? 'archive' : 'forecast';
    const endpoint = source === 'archive'
      ? 'https://archive-api.open-meteo.com/v1/archive'
      : 'https://api.open-meteo.com/v1/forecast';
    const params = new URLSearchParams({
      latitude: String(LATITUDE),
      longitude: String(LONGITUDE),
      hourly: 'temperature_2m,precipitation,snowfall',
      timezone: 'Asia/Seoul',
    });

    if (source === 'archive') {
      params.set('start_date', date);
      params.set('end_date', date);
    } else {
      params.set('forecast_days', '16');
    }

    const controller = new AbortController();
    const timeout = root.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const response = await root.fetch(`${endpoint}?${params.toString()}`, {
        method: 'GET',
        signal: controller.signal,
        headers: { Accept: 'application/json' },
      });
      if (!response.ok) {
        return unavailable(date, '날씨 자료를 제공하지 않는 날짜입니다.');
      }

      const payload = await response.json();
      const hourly = payload.hourly || {};
      const selectedIndexes = (hourly.time || [])
        .map((time, index) => time.startsWith(`${date}T`) ? index : -1)
        .filter(index => index >= 0);

      if (selectedIndexes.length !== 24) {
        return unavailable(date, '선택한 날짜의 시간별 날씨 자료가 없습니다.');
      }

      const pick = key => selectedIndexes.map(index => {
        const value = hourly[key]?.[index];
        return Number.isFinite(value) ? value : null;
      });
      const result = {
        available: true,
        date,
        source,
        cached: false,
        hourly: {
          time: selectedIndexes.map(index => hourly.time[index]),
          temperature_2m: pick('temperature_2m'),
          precipitation: pick('precipitation'),
          snowfall: pick('snowfall'),
        },
      };
      writeCached(result);
      return result;
    } catch (_) {
      return unavailable(date, '날씨를 불러오지 못했습니다. 연결 상태를 확인해 주세요.');
    } finally {
      root.clearTimeout(timeout);
    }
  }

  function fetchForDate(date) {
    if (!isValidDateString(date)) {
      return Promise.resolve(unavailable(date, '날짜 형식이 올바르지 않습니다.'));
    }

    const cached = readCached(date);
    if (cached) return Promise.resolve(cached);

    const existing = inFlight.get(date);
    if (existing) return existing;

    if (pendingRequest?.date === date) return pendingRequest.promise;
    if (pendingRequest) {
      settlePendingAsUnavailable('날짜 선택이 바뀌어 이전 요청을 취소했습니다.');
    }

    const today = todayInSeoul();
    const maximumForecastDate = addDays(today, 15);
    if (date >= today && date > maximumForecastDate) {
      return Promise.resolve(unavailable(date, `예보는 ${today}부터 ${maximumForecastDate}까지 제공됩니다.`));
    }

    let resolve;
    const promise = new Promise(done => { resolve = done; });
    pendingRequest = { date, promise, resolve };
    scheduleDispatch(DEBOUNCE_MS);
    return promise;
  }

  root.WeatherClient = Object.freeze({
    fetchForDate,
    getToday: todayInSeoul,
    getMaxForecastDate: () => addDays(todayInSeoul(), 15),
  });
})(window);
