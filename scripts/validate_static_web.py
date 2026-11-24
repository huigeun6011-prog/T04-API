"""Offline Python/Node parity checks; no API calls, training, or persistent fixtures."""
from __future__ import annotations
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
import prediction_api as api
from build_static_web import T04_PUBLIC_FILES, export_model, export_runtime, build


def main():
    rng = np.random.default_rng(411)
    m = api.get_model()
    model, runtime = export_model(), export_runtime()
    rows = [[int(rng.integers(0,22)), int(rng.integers(5,25)), int(rng.integers(2)), int(rng.integers(2)), float(rng.uniform(-20,40)), float(rng.uniform(0,40)), float(rng.uniform(0,15)), int(rng.integers(2))] for _ in range(300)]
    base = [10, 18, 0, 0, 15., 0., 0., 1]
    for idx in range(8):
        for value in (np.nan, -1., 256., 0.5, 1.e9):
            row = base.copy(); row[idx] = value; rows.append(row)
    # Check every numerical split at its exact double and both adjacent doubles.
    for tree in model['trees']:
        for node in tree['nodes']:
            if node[6] or node[7] or node[2] == 'Infinity':
                continue
            original = model['input_order'][node[1]]
            for v in (np.nextafter(node[2], -np.inf), node[2], np.nextafter(node[2], np.inf)):
                row = base.copy(); row[original] = v; rows.append(row)
    expected = m.predict(pd.DataFrame(rows, columns=api.FEATURES)).tolist()
    cases = []
    for d in ('2025-01-01', '2025-02-10', '2026-03-27', '2026-03-30', '2026-04-04', '2026-05-05'):
        for start, end in ((5,8),(17,20),(23,24)):
            for extra in ({}, {'min_stops':2,'max_stops':12,'max_walk_minutes':25}, {'category':'park','max_walk_minutes':10}):
                cases.append(dict(date=d,start_hour=start,end_hour=end,origin=api.stations()[10],**extra))
    for station in (0, 5, 16, 21):
        for extra in ({}, {'category':'library','min_stops':1}, {'category':'bookstore','max_stops':4}):
            cases.append(dict(date='2026-03-30',start_hour=5,end_hour=24,origin=api.stations()[station],**extra))
    weather = {}
    for path in (ROOT/'data/raw/weather').glob('????-??-??.json'):
        raw = json.loads(path.read_text(encoding='utf-8'))['hourly']
        weather[path.stem] = {k:raw[k] for k in ('time','temperature_2m','precipitation','snowfall')}
    # Ensure reference execution cannot reach the network either.
    original_weather = api.weather_day
    api.weather_day = lambda d: (weather[d], 'local_archive')
    try:
        reference = [api.recommend(c) for c in cases]
    finally:
        api.weather_day = original_weather
    rounded_inputs = [2.675, 1.25, 1.35, -1.25, 0.5, 1.5, 2.5, 1234.5675]
    with tempfile.TemporaryDirectory(prefix='static-parity-') as temp:
        tmp = Path(temp)
        clean_rows = [[None if np.isnan(v) else v for v in row] for row in rows]
        (tmp/'input.json').write_text(json.dumps(dict(model=model,runtime=runtime,rows=clean_rows,cases=cases,weather=weather,rounded=rounded_inputs),ensure_ascii=False,allow_nan=False),encoding='utf-8')
        program = r'''
const fs=require('fs'), assert=require('assert');
const api=require(process.argv[1]), data=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
(async()=>{
  const engine=api.createEngine({resources:data,weather:async d=>data.weather[d]});
  const predictions=data.rows.map(r=>api.predict(data.model,r));
  const results=[]; for(const c of data.cases) results.push(await engine.recommend(c));
  let reads=0, done;
  const delayed=api.createEngine({weather:async d=>{reads++;await new Promise(r=>done=r);return data.weather[d]}});
  const a=new AbortController(); const p=delayed.fetchWeatherForDate(data.cases[0].date,{signal:a.signal});
  const q=delayed.fetchWeatherForDate(data.cases[0].date);a.abort();done();
  await assert.rejects(p,{name:'AbortError'});assert.equal((await q).available,true);assert.equal(reads,1);
  assert.equal((await delayed.fetchWeatherForDate(data.cases[0].date)).cached,true);
  const urls=[]; const relative=api.createEngine({baseURL:'https://example.test/project/',fetch:async url=>{urls.push(url);return {ok:true,json:async()=>url.endsWith('model.json')?data.model:data.runtime}}});
  await relative.preload(); assert(urls.every(u=>u.startsWith('https://example.test/project/data/')));
  const calls=[];
  const remote=api.createEngine({baseURL:'https://example.test/sub/',now:()=>Date.parse('2026-11-22T16:00:00Z'),minRequestIntervalMs:0,fetch:async url=>{
    calls.push(url); if(url.startsWith('https://example.test')) return {ok:false};
    const day=new URL(url).searchParams.get('start_date');
    return {ok:true,json:async()=>({hourly:{time:Array.from({length:24},(_,h)=>`${day}T${String(h).padStart(2,'0')}:00`),temperature_2m:Array(24).fill(10),precipitation:Array(24).fill(0),snowfall:Array(24).fill(0)}})};
  }});
  assert.equal((await remote.fetchWeatherForDate('2026-11-23')).source,'forecast');
  assert.equal((await remote.fetchWeatherForDate('2026-11-22')).source,'archive');
  const beyondForecast=await remote.fetchWeatherForDate('2026-12-09');
  assert.equal(beyondForecast.available,true);
  assert.equal(beyondForecast.source,'fallback');
  assert.equal(beyondForecast.fallback.source_date,'2026-11-23');
  assert.equal(beyondForecast.fallback.requested_date,'2026-12-09');
  assert.equal((await remote.fetchWeatherForDate('2026-02-30')).available,false);
  const count=calls.length;await remote.fetchWeatherForDate('2026-11-23');assert.equal(calls.length,count);
  const timeout=api.createEngine({timeoutMs:5,minRequestIntervalMs:0,fetch:async(url,{signal})=>new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(new Error('timeout'))))});
  assert.equal((await timeout.fetchWeatherForDate('2025-01-01')).available,false);
  console.log(JSON.stringify({predictions,results,rounds:data.rounded.map(v=>[0,1,2,3].map(n=>api.round(v,n)))}));
})().catch(e=>{console.error(e);process.exit(1)});
'''
        result = subprocess.run(['node','-e',program,str(ROOT/'static_src/static-engine.js'),str(tmp/'input.json')],capture_output=True,text=True,encoding='utf-8',check=True)
        actual = json.loads(result.stdout)
        errors = np.abs(np.array(expected)-actual['predictions'])
        assert float(errors.max()) <= 1e-10, float(errors.max())
        assert actual['rounds'] == [[round(v,n) for n in (0,1,2,3)] for v in rounded_inputs]
        def compare(a,b,path=''):
            if isinstance(a,dict):
                assert a.keys()==b.keys(), (path,a.keys(),b.keys())
                for k in a: compare(a[k],b[k],path+'/'+k)
            elif isinstance(a,list):
                assert len(a)==len(b),(path,len(a),len(b))
                for i,(x,y) in enumerate(zip(a,b)): compare(x,y,path+f'/{i}')
            elif isinstance(a,float):
                assert abs(a-b)<=1e-10,(path,a,b)
            else: assert a==b,(path,a,b)
        compare(reference,actual['results'])
        # Package checks also verify existing user configuration is left untouched.
        if (ROOT/'static_src/index.html').exists() and (ROOT/'static_src/app.js').exists():
            site=tmp/'site'; site.mkdir()
            (site/'config.local.js').write_text('user sentinel',encoding='utf-8')
            build(site)
            assert (site/'config.local.js').read_text(encoding='utf-8')=='user sentinel'
            assert not list(site.rglob('*.joblib')) and not list(site.rglob('*.py'))
            for name in ('t04-core.js', 'weather-daily.js', 'weather-daily-view.js', 'weather-daily.css'):
                assert (site / name).is_file(), f'Missing static T04 file: {name}'
            for name in T04_PUBLIC_FILES:
                assert (site / 'data/t04' / name).is_file(), f'Missing static T04 data file: {name}'
    print(f'PASS: {len(rows)} feature rows, {len(cases)} full recommendations; maximum prediction error={errors.max():.3g}; rounding, shared cancellation/cache, subpath URLs verified')


if __name__ == '__main__':
    main()
