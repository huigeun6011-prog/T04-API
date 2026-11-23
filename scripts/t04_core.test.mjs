import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import { isDeepStrictEqual } from 'node:util';
import { runInNewContext } from 'node:vm';

import { upsert } from './t04_daily_record.mjs';

const require = createRequire(import.meta.url);
const core = require('../static_src/t04-core.js');
const assets = new URL(
  '../data/external/t04_assets/extracted/t04-real-information-board-public-v1/',
  import.meta.url
);

async function readAsset(path) {
  const url = new URL(path, assets);
  try {
    return JSON.parse(await readFile(url, 'utf8'));
  } catch (error) {
    throw new Error(`Cannot load T04 public fixture asset ${url.href}. Extract the public package first. ${error.message}`,
      { cause: error });
  }
}

async function loadFixtures() {
  const manifest = await readAsset('fixture-manifest.json');
  assert.equal(manifest.fixtures.length, 9);
  const entries = await Promise.all(manifest.fixtures.map(async ({ file, fixture_id }) => {
    const fixture = await readAsset(`fixtures/${file}`);
    assert.equal(fixture.fixture_id, fixture_id);
    return [fixture_id, fixture];
  }));
  const fixtures = new Map(entries);
  assert.equal(fixtures.size, 9);
  return fixtures;
}

function replay(fixtures, sequence) {
  let state = core.resetState();
  const recordIds = new Map();
  for (const id of sequence) {
    const fixture = fixtures.get(id);
    assert.ok(fixture, `Missing fixture ${id}`);
    const previous = state;
    state = core.runFixture(previous, fixture);
    const summary = core.describe(state);
    const row = state.daily_readings.find((entry) =>
      entry.signal_id === state.current_reading?.signal_id && entry.record_date === summary.record_date
    );
    const expected = fixture.expected;
    const referenceId = expected.same_record_id_as;
    if (referenceId) assert.ok(recordIds.has(referenceId), `${id}: missing earlier record ${referenceId}`);
    const preservesLastGood = state.status.freshness === 'stale'
      ? isDeepStrictEqual(state.current_reading, previous.current_reading) &&
        isDeepStrictEqual(state.daily_readings, previous.daily_readings)
      : isDeepStrictEqual(state.current_reading, fixture.payload) &&
        isDeepStrictEqual(row?.reading, fixture.payload);
    const actual = {
      ...summary,
      preserve_last_good: preservesLastGood,
      same_record_id_as: row?.record_id === recordIds.get(referenceId) ? referenceId : null
    };
    for (const [key, value] of Object.entries(expected)) {
      assert.deepEqual(actual[key], value, `${id}: ${key}`);
    }
    assert.ok(row?.record_id, `${id}: daily record ID`);
    recordIds.set(id, row.record_id);
  }
  return state;
}

test('all nine public fixtures match every expected field in the contracted sequences', async (t) => {
  const fixtures = await loadFixtures();
  const { success, baseline, failures, recovery } = core.FIXTURE_ORDER;
  const contract = (await readAsset('public-contract.json')).fixture_contract;
  assert.deepEqual(success, contract.success_sequence);
  assert.deepEqual(baseline, contract.failure_baseline_sequence);
  assert.deepEqual(failures, contract.failure_fixtures);
  assert.deepEqual(recovery, contract.recovery_sequence);
  assert.deepEqual(new Set([...success, ...failures, ...recovery]), new Set(fixtures.keys()));

  await t.test('success sequence', () => replay(fixtures, success));
  for (const id of failures) {
    await t.test(id, () => {
      const state = replay(fixtures, [...baseline, id]);
      assert.equal(core.describe(state).last_good_value, 105);
      assert.equal(core.describe(state).retry_after_seconds, id === 'T04-RATE-429' ? 60 : null);
    });
  }
  await t.test('recovery sequence', () => {
    const state = replay(fixtures, recovery);
    assert.deepEqual(state.daily_readings.map((row) => row.record_date), ['2026-08-24', '2026-08-25']);
    assert.deepEqual(core.describe(state).comparison,
      { state: 'comparable', direction: 'increase', magnitude: 15, unit: 'pt' });
    assert.equal(core.describe(state).retry_after_seconds, null);
  });
});

function mockReading(fetchedAt, value, unit = '°C') {
  return {
    signal_id: 'daejeon-temperature-2m',
    normalized_value: value,
    unit,
    source_name: 'Mock weather',
    source_url: 'https://weather.example.test/',
    source_time: null,
    fetched_at: fetchedAt,
    record_timezone: 'Asia/Seoul',
    record_date: core.kstDate(fetchedAt)
  };
}

test('C20 and C21 keep one row for three KST same-day successes and add one at KST midnight', () => {
  const times = [
    '2026-09-01T15:00:00Z', '2026-09-02T00:00:00Z',
    '2026-09-02T14:59:59Z', '2026-09-02T15:00:00Z'
  ];
  const now = () => times.shift();
  const first = core.applySuccessfulReading(core.resetState(), mockReading(now(), 12));
  const second = core.applySuccessfulReading(first, mockReading(now(), 13));
  const third = core.applySuccessfulReading(second, mockReading(now(), 14));
  const nextDay = mockReading(now(), 11);
  const fourth = core.applySuccessfulReading(third, nextDay);

  for (const [state, value] of [[first, 12], [second, 13], [third, 14]]) {
    assert.equal(core.describe(state).row_count, 1);
    assert.equal(core.describe(state).stored_value, value);
    assert.equal(state.daily_readings[0].record_id, first.daily_readings[0].record_id);
    assert.equal(state.daily_readings[0].first_fetched_at, first.current_reading.fetched_at);
  }
  assert.deepEqual(fourth.daily_readings.map((row) => row.record_date), ['2026-09-02', '2026-09-03']);
  assert.deepEqual(core.describe(fourth).comparison,
    { state: 'comparable', direction: 'decrease', magnitude: 3, unit: '°C' });
  assert.deepEqual(core.comparisonFor(third.daily_readings, { ...nextDay, unit: '°F' }),
    { state: 'unit_mismatch', direction: null, magnitude: null, unit: null });
});

test('C26 replay failures and reset use only synthetic state, independent of the daily recorder', async () => {
  const live = { reading: mockReading('2026-08-24T00:00:00Z', 21), raw: { current: { temperature_2m: 21 } } };
  const liveRows = upsert([], live);
  const saved = structuredClone(liveRows);
  const fixtures = await loadFixtures();
  for (const id of core.FIXTURE_ORDER.failures) {
    const replayed = replay(fixtures, [...core.FIXTURE_ORDER.baseline, id]);
    assert.equal(replayed.current_reading.signal_id, 'aleph-demo-index');
    assert.equal(replayed.current_reading.normalized_value, 105);
    assert.notStrictEqual(replayed.daily_readings, liveRows);
    assert.deepEqual(core.resetState().daily_readings, []);
  }
  assert.deepEqual(liveRows, saved);
});

test('the browser build exposes the same API on T04Core', async () => {
  const source = await readFile(new URL('../static_src/t04-core.js', import.meta.url), 'utf8');
  const browser = {};
  runInNewContext(source, browser);
  assert.deepEqual(Object.keys(browser.T04Core), Object.keys(core));
  assert.equal(browser.T04Core.resetState().schema_version, 'aleph-t04-evaluation-state-v1');
});
