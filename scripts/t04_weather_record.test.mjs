import test from 'node:test';
import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { copyFile, mkdir, mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { promisify } from 'node:util';
import { recordToday } from './t04_weather_record.mjs';
import Weather from '../static_src/weather-daily.js';
import Core from '../static_src/t04-core.js';

const fixturePath = new URL('../static-web/data/t04/fixtures/', import.meta.url);
const fixture = async (name) => JSON.parse(await readFile(new URL(`${name}.json`, fixturePath), 'utf8'));
const archiveFixture = async (name) => {
  const forecast = Weather.fromFixture(await fixture(name));
  const { record_date, fetched_at } = forecast.reading;
  const day = new Date(`${record_date}T00:00:00Z`);
  day.setUTCDate(day.getUTCDate() - 1);
  const dataDate = day.toISOString().slice(0, 10);
  const raw = structuredClone(forecast.raw);
  raw.hourly.time = raw.hourly.time.map((time) => dataDate + time.slice(10));
  return Weather.normalize(raw, fetched_at, { dataDate });
};
const observedOptions = (record) => ({
  now: () => new Date(record.reading.fetched_at),
  fetchImpl: async () => new Response(JSON.stringify(record.raw))
});

test('public fixtures drive five weather failures and full hourly recovery', async () => {
  const first = Weather.fromFixture(await fixture('normal-d1-a'));
  const updated = Weather.fromFixture(await fixture('normal-d1-b'));
  let rows = Weather.upsert(Weather.upsert([], first), updated);
  assert.equal(rows.length, 1);
  for (const [file, kind] of [
    ['timeout', 'timeout'], ['auth-401', 'auth'], ['rate-429', 'rate_limit'],
    ['offline', 'offline'], ['schema-break', 'schema_error']
  ]) {
    const input = await fixture(file);
    assert.throws(() => Weather.fromFixture(input), { kind });
    assert.deepEqual(rows, [updated]);
  }
  const recovered = Weather.fromFixture(await fixture('recover-d2'));
  rows = Weather.upsert(rows, recovered);
  assert.equal(rows.length, 2);
  assert.ok(recovered.raw.hourly.temperature_2m.every((value, i) => value !== updated.raw.hourly.temperature_2m[i]));
  assert.ok(Object.keys(recovered.summary).every((key) => recovered.summary[key] !== updated.summary[key]));
  assert.equal(Core.roundToTenth(recovered.summary.mean - updated.summary.mean), 3.7);
  assert.deepEqual(Weather.readRows({ rows }), rows);
  assert.equal(Weather.kindOf(recovered), 'forecast');
  assert.equal(Weather.dataDateOf(recovered), recovered.reading.record_date);
});

test('Archive recorder keeps one row per actual KST lookup date and preserves files when pending', async () => {
  const dir = await mkdtemp(join(tmpdir(), 't04-weather-'));
  const path = join(dir, 'daily.json');
  const first = await archiveFixture('normal-d1-a');
  const second = await archiveFixture('recover-d2');
  const request = (record) => ({
    now: () => new Date(record.reading.fetched_at),
    fetchImpl: async (url, options) => {
      assert.equal(url, Weather.archiveUrl(Weather.dataDateOf(record)));
      assert.equal(options.cache, 'no-store');
      return new Response(JSON.stringify(record.raw));
    }
  });
  try {
    assert.equal((await recordToday(path, request(first))).count, 1);
    assert.equal((await recordToday(path, request(first))).count, 1);
    assert.equal((await recordToday(path, request(second))).count, 2);
    const bytes = await readFile(path, 'utf8');
    const rows = Weather.readRows(JSON.parse(bytes));
    assert.deepEqual(rows, [first, second]);
    assert.equal(Weather.kindOf(first), 'observed');
    assert.equal(Weather.latestRow([second, first]), second);
    assert.equal(Weather.latestRow([]), null);
    const corrupt = structuredClone(second.raw);
    corrupt.hourly.temperature_2m[23] = null;
    await assert.rejects(recordToday(path, { ...request(second), fetchImpl: async () => new Response(JSON.stringify(corrupt)) }),
      { kind: 'pending', date: second.reading.record_date, dataDate: Weather.dataDateOf(second) });
    assert.equal(await readFile(path, 'utf8'), bytes);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('Archive and forecast rows enforce different data dates without changing today forecast requests', async () => {
  const observed = await archiveFixture('normal-d1-a');
  const { reading, raw } = observed;
  const date = Weather.dataDateOf(observed);
  assert.equal(reading.record_date, '2026-08-24');
  assert.equal(date, '2026-08-23');
  assert.equal(reading.source_time, '2026-08-23T00:00:00+09:00');
  assert.equal(reading.source_name, 'Open-Meteo 대전 관측(archive)');
  const url = new URL(Weather.archiveUrl(date));
  assert.equal(url.origin + url.pathname, 'https://archive-api.open-meteo.com/v1/archive');
  assert.deepEqual(Object.fromEntries(url.searchParams), {
    latitude: '36.35', longitude: '127.38', hourly: 'temperature_2m,precipitation,snowfall',
    timezone: 'Asia/Seoul', start_date: date, end_date: date
  });
  assert.throws(() => Weather.normalize(raw, reading.fetched_at, { dataDate: '2026-08-22' }), TypeError);
  const invalidSource = { ...observed, reading: { ...reading, source_time: '2026-08-24T00:00:00+09:00' } };
  assert.throws(() => Weather.validateRecord(invalidSource), TypeError);
  const invalidSummary = { ...observed, summary: { ...observed.summary, mean: 100 } };
  assert.throws(() => Weather.validateRecord(invalidSummary), TypeError);
  const wrongHour = structuredClone(raw);
  wrongHour.hourly.time[0] = '2026-08-24T00:00';
  await assert.rejects(Weather.requestObserved(observedOptions({ ...observed, raw: wrongHour })), TypeError);
  const wrongUnits = structuredClone(raw);
  wrongUnits.hourly_units.temperature_2m = '°F';
  await assert.rejects(Weather.requestObserved(observedOptions({ ...observed, raw: wrongUnits })), TypeError);

  const fixtureRow = Weather.fromFixture(await fixture('normal-d1-a'));
  const forecast = await Weather.requestToday({
    ...observedOptions(fixtureRow),
    fetchImpl: async (address) => {
      const forecastUrl = new URL(address);
      assert.equal(forecastUrl.hostname, 'api.open-meteo.com');
      assert.equal(forecastUrl.searchParams.get('start_date'), reading.record_date);
      return new Response(JSON.stringify(fixtureRow.raw));
    }
  });
  assert.equal(Weather.kindOf(forecast), 'forecast');
  assert.equal(Weather.dataDateOf(forecast), reading.record_date);
  assert.deepEqual(Weather.validateRecord(forecast), forecast);
});

test('Archive classifies absent data as pending and preserves other HTTP and transport errors', async () => {
  const record = await archiveFixture('normal-d1-a');
  const options = observedOptions(record);
  const short = structuredClone(record.raw);
  for (const column of Object.values(short.hourly)) column.pop();
  await assert.rejects(Weather.requestObserved(observedOptions({ ...record, raw: short })), { kind: 'pending' });
  for (const [status, body, kind] of [
    [204, null, 'pending'],
    [400, JSON.stringify({ reason: "Parameter 'start_date' is out of allowed range" }), 'pending'],
    [400, JSON.stringify({ reason: 'Invalid latitude' }), 'schema_error'],
    [401, null, 'auth'], [429, null, 'rate_limit'], [503, null, 'offline']
  ]) {
    await assert.rejects(Weather.requestObserved({
      ...options,
      fetchImpl: async () => new Response(body, { status, headers: { 'Retry-After': '60' } })
    }), { kind });
  }
  await assert.rejects(Weather.requestObserved({
    ...options, fetchImpl: async () => { throw new Error('offline'); }
  }), { kind: 'offline' });
});

test('CLI records, skips, forces and leaves pending data unwritten', async (t) => {
  const dir = await mkdtemp(join(tmpdir(), 't04-weather-cli-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  await Promise.all(['scripts', 'static_src'].map((name) => mkdir(join(dir, name))));
  await Promise.all([
    'scripts/t04_weather_record.mjs', 'static_src/weather-daily.js', 'static_src/t04-core.js'
  ].map((file) => copyFile(new URL(`../${file}`, import.meta.url), join(dir, file))));
  const file = join(dir, 'static-web', Weather.recordPath);
  const first = await archiveFixture('normal-d1-a');
  const changed = await archiveFixture('normal-d1-b');
  async function run(record, { args = [], force = '0' } = {}) {
    const timestamp = record?.reading.fetched_at ?? first.reading.fetched_at;
    const preload = `
      const RealDate = Date;
      globalThis.Date = class extends RealDate {
        constructor(...args) { super(...(args.length ? args : [${JSON.stringify(timestamp)}])); }
      };
      globalThis.fetch = async () => {
        if (${!record}) throw new Error('Unexpected Archive request');
        return new Response(${JSON.stringify(JSON.stringify(record?.raw ?? null))});
      };
    `;
    const { stdout } = await promisify(execFile)(process.execPath, [
      '--import', `data:text/javascript,${encodeURIComponent(preload)}`,
      'scripts/t04_weather_record.mjs', ...args
    ], { cwd: dir, env: { ...process.env, FORCE: force } });
    return stdout;
  }
  const date = first.reading.record_date;
  const dataDate = Weather.dataDateOf(first);
  const pending = { reading: first.reading, raw: {} };
  assert.match(await run(pending), new RegExp(`PENDING date=${date} data_date=${dataDate}`));
  await assert.rejects(readFile(file), { code: 'ENOENT' });
  assert.match(await run(first), new RegExp(`RECORDED date=${date}`));
  const bytes = await readFile(file);
  assert.equal((await run(null)).trim(), `SKIPPED date=${date} (이미 기록됨)`);
  assert.deepEqual(await readFile(file), bytes);
  assert.match(await run(changed, { args: ['--force'] }), new RegExp(`RECORDED date=${date}`));
  assert.deepEqual(Weather.readRows(JSON.parse(await readFile(file))), [changed]);
  assert.match(await run(first, { force: '1' }), new RegExp(`RECORDED date=${date}`));
  assert.match(await run(pending, { args: ['--force'] }), new RegExp(`PENDING date=${date}`));
  await assert.rejects(run(null, { args: ['--force'] }), { code: 1, stderr: /FAILED offline/ });
  assert.deepEqual(await readFile(file), bytes);
});
