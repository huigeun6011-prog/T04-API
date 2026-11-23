import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { recordToday } from './t04_weather_record.mjs';
import Weather from '../static_src/weather-daily.js';
import Core from '../static_src/t04-core.js';

const fixturePath = new URL('../static-web/data/t04/fixtures/', import.meta.url);
const fixture = async (name) => JSON.parse(await readFile(new URL(`${name}.json`, fixturePath), 'utf8'));

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
});

test('manual live-response path validates and stores exactly one record per KST date', async () => {
  const dir = await mkdtemp(join(tmpdir(), 't04-weather-'));
  const path = join(dir, 'daily.json');
  const first = Weather.fromFixture(await fixture('normal-d1-a'));
  const second = Weather.fromFixture(await fixture('recover-d2'));
  const request = (record) => ({
    now: () => new Date(record.reading.fetched_at),
    fetchImpl: async (url, options) => {
      assert.equal(new URL(url).searchParams.get('timezone'), 'Asia/Seoul');
      assert.equal(new URL(url).searchParams.get('start_date'), record.reading.record_date);
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
    assert.deepEqual(rows.map(({ summary }) => summary), [first.summary, second.summary]);
    const corrupt = structuredClone(second.raw);
    corrupt.hourly.temperature_2m[23] = null;
    await assert.rejects(recordToday(path, { ...request(second), fetchImpl: async () => new Response(JSON.stringify(corrupt)) }), TypeError);
    assert.equal(await readFile(path, 'utf8'), bytes);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});
