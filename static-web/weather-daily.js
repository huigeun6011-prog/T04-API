(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(require('./t04-core.js'));
  else root.DailyWeather = factory(root.T04Core);
})(globalThis, function (Core) {
  'use strict';

  const timezone = 'Asia/Seoul';
  const units = { temperature_2m: '°C', precipitation: 'mm', snowfall: 'cm' };
  const fields = Object.keys(units);
  const signal = 'daejeon-daily-mean-temperature';
  const endpoint = 'https://api.open-meteo.com/v1/forecast';
  const recordPath = 'data/t04/weather-daily.json';
  const dateHours = (date) => Array.from({ length: 24 }, (_, hour) => `${date}T${String(hour).padStart(2, '0')}:00`);

  function sourceUrl(date) {
    const params = new URLSearchParams({
      latitude: '36.35', longitude: '127.38', hourly: fields.join(','),
      timezone, start_date: date, end_date: date
    });
    return `${endpoint}?${params}`;
  }

  function normalize(raw, fetchedAt, { synthetic = false } = {}) {
    const date = Core.kstDate(fetchedAt);
    const expectedTimes = dateHours(date);
    const hourly = raw?.hourly;
    if (raw?.timezone !== timezone || !Array.isArray(hourly?.time) || hourly.time.length !== 24 ||
        !expectedTimes.every((time, i) => hourly.time[i] === time) ||
        !fields.every((field) => raw.hourly_units?.[field] === units[field] &&
          Array.isArray(hourly[field]) && hourly[field].length === 24 &&
          hourly[field].every((value) => Number.isFinite(value) && (field === 'temperature_2m' || value >= 0)))) {
      throw new TypeError('대전의 KST 00~23시 날씨 또는 단위 형식이 올바르지 않습니다.');
    }
    const sum = (values) => values.reduce((total, value) => total + value, 0);
    const round = Core.roundToTenth;
    const temperatures = hourly.temperature_2m;
    const summary = {
      mean: round(sum(temperatures) / 24),
      min: round(Math.min(...temperatures)),
      max: round(Math.max(...temperatures)),
      precipitation: round(sum(hourly.precipitation)),
      snowfall: round(sum(hourly.snowfall))
    };
    const reading = {
      signal_id: signal, normalized_value: summary.mean, unit: '°C',
      source_name: synthetic ? 'ALEPH 합성 날씨' : 'Open-Meteo 대전 예보',
      source_url: synthetic ? 'https://fixtures.aleph.invalid/t04/weather' : sourceUrl(date),
      source_time: `${date}T00:00:00+09:00`, fetched_at: new Date(fetchedAt).toISOString(),
      record_timezone: timezone, record_date: date
    };
    Core.validateNormalizedReading(reading);
    return { reading, summary, raw };
  }

  function validateRecord(record) {
    const normalized = normalize(record?.raw, record?.reading?.fetched_at);
    for (const field of ['reading', 'summary']) {
      if (!Object.entries(normalized[field]).every(([key, value]) => record[field]?.[key] === value)) {
        throw new TypeError('저장한 날씨 값과 원본 응답의 계산값이 다릅니다.');
      }
    }
    return normalized;
  }

  function readRows(doc) {
    if (!Array.isArray(doc?.rows)) throw new TypeError('일별 날씨 기록 형식이 올바르지 않습니다.');
    const rows = doc.rows.map(validateRecord).sort((a, b) => a.reading.record_date.localeCompare(b.reading.record_date));
    if (new Set(rows.map((row) => row.reading.record_date)).size !== rows.length) {
      throw new TypeError('일별 날씨 기록에 중복 날짜가 있습니다.');
    }
    return rows;
  }

  function upsert(rows, record) {
    const date = record.reading.record_date;
    return [...rows.filter((row) => row.reading.record_date !== date), record]
      .sort((a, b) => a.reading.record_date.localeCompare(b.reading.record_date));
  }

  async function requestToday({ fetchImpl = fetch, now = () => new Date(), signal } = {}) {
    const date = Core.kstDate(now());
    let response;
    try {
      response = await fetchImpl(sourceUrl(date), { cache: 'no-store', signal });
    } catch (error) {
      const kind = signal?.aborted || error.name === 'TimeoutError' ? 'timeout' : 'offline';
      throw Object.assign(new Error('날씨 API에 연결하지 못했습니다.'), { kind });
    }
    if (!response.ok) {
      const kind = {401: 'auth', 403: 'auth', 408: 'timeout', 429: 'rate_limit', 504: 'timeout'}[response.status]
        || (response.status >= 500 ? 'offline' : 'schema_error');
      throw Object.assign(new Error(`Open-Meteo HTTP ${response.status}`), { kind, retryAfter: response.headers.get('Retry-After') });
    }
    const raw = await response.json();
    const fetchedAt = now();
    if (date !== Core.kstDate(fetchedAt)) throw Object.assign(new Error('조회 중 날짜가 바뀌었습니다. 다시 시도해 주세요.'), { kind: 'schema_error' });
    return normalize(raw, fetchedAt);
  }

  function fromFixture(fixture) {
    const replay = Core.runFixture(Core.resetState(), fixture);
    if (replay.status.error_code !== 'none') {
      const kind = replay.status.error_code;
      throw Object.assign(new Error(Core.ERROR_INFO[kind].label), { kind, retryAfter: replay.last_run.retry_after_seconds });
    }
    const source = fixture.payload;
    const date = Core.kstDate(source.fetched_at);
    const variant = source.normalized_value;
    // Translate the public fixture's successful signal into deterministic hourly weather.
    const time = dateHours(date);
    const base = 6 + (variant - 100) / 4;
    const hourly = {
      time,
      temperature_2m: time.map((_, i) => Core.roundToTenth(base + (i - 11.5) * (variant === 100 ? 0.2 : 0.24))),
      precipitation: time.map((_, i) => i < 3 ? Core.roundToTenth((variant - 95) / 25) : 0),
      snowfall: time.map((_, i) => i < 2 ? Core.roundToTenth((variant - 100) / 20) : 0)
    };
    return normalize({ timezone, hourly_units: units, hourly }, source.fetched_at, { synthetic: true });
  }

  return { recordPath, normalize, validateRecord, readRows, upsert, requestToday, fromFixture };
});
