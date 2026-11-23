"""Export the trusted fitted HGB and assemble a Python-free static site.

Run: python scripts/build_static_web.py [--output static-web]
No training, credentials, labels, or raw training tables are included.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import prediction_api as api
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn._loss.loss import HalfSquaredError

T04_ASSETS = ROOT / 'data/external/t04_assets/extracted/t04-real-information-board-public-v1'
T04_FIXTURES = tuple(f'fixtures/{name}.json' for name in (
    'auth-401', 'normal-d1-a', 'normal-d1-b', 'normal-d2', 'offline',
    'rate-429', 'recover-d2', 'schema-break', 'timeout',
))
T04_PUBLIC_FILES = ('asset-manifest.json', 'fixture-manifest.json', 'public-contract.json', *T04_FIXTURES)


def read_t04_assets():
    if not T04_ASSETS.is_dir():
        raise FileNotFoundError(f'Missing T04 public asset directory: {T04_ASSETS}')

    def read_asset(name):
        path = T04_ASSETS / name
        if not path.is_file():
            raise FileNotFoundError(f'Missing T04 public asset: {path}')
        return path.read_bytes()

    manifest_name = 'asset-manifest.json'
    manifest_bytes = read_asset(manifest_name)
    manifest = json.loads(manifest_bytes)
    hashes = {entry['path']: entry['sha256'] for entry in manifest['files']}
    public_files = set(T04_PUBLIC_FILES) - {manifest_name}
    public_files.update(f'fixtures/{path.name}' for path in (T04_ASSETS / 'fixtures').glob('*.json'))
    reference_files = {'README.md', 'adapter-reset.example.js', 'criterion-registry.json',
                       'fixture.schema.json', 'normalized-reading.schema.json', 'reading-status.schema.json'}
    assets = {manifest_name: manifest_bytes}
    for name in sorted(public_files | reference_files):
        content = read_asset(name)
        if name not in hashes:
            raise ValueError(f'T04 asset-manifest.json has no SHA-256 for {name}')
        actual = hashlib.sha256(content).hexdigest()
        if actual != hashes[name]:
            raise ValueError(f'T04 asset SHA-256 mismatch for {name}: expected {hashes[name]}, got {actual}')
        if name in public_files:
            assets[name] = content
    return assets


def export_model():
    model = api.get_model()  # trusted, checked-in local joblib only
    if type(model) is not HistGradientBoostingRegressor or type(model._loss) is not HalfSquaredError:
        raise ValueError('Unsupported model: expected squared-error HistGradientBoostingRegressor')
    if list(model.feature_names_in_) != api.FEATURES or model.n_trees_per_iteration_ != 1:
        raise ValueError('Unsupported model feature/output layout')
    cats = np.flatnonzero(model.is_categorical_).tolist()
    nums = np.flatnonzero(~model.is_categorical_).tolist()
    if cats != [0, 2, 3, 7] or model._preprocessor is None:
        raise ValueError('Unsupported categorical preprocessing')
    encoder = model._preprocessor.named_transformers_['encoder']
    if encoder.handle_unknown != 'use_encoded_value' or not np.isnan(encoder.unknown_value):
        raise ValueError('Unsupported ordinal encoder')
    categories = [c.tolist() for c in encoder.categories_]
    if any(not np.isfinite(c).all() for c in encoder.categories_):
        raise ValueError('Unsupported nonfinite category')
    if list(model._preprocessor.transformers_[0][2]) != list(model.is_categorical_):
        raise ValueError('Unsupported column remapping')
    if not np.array_equal(model._is_categorical_remapped, [True]*4 + [False]*4):
        raise ValueError('Unsupported internal feature order')
    for known, category in zip(model._bin_mapper.known_categories[:4], categories):
        if not np.array_equal(known, np.arange(len(category))):
            raise ValueError('Unsupported raw categorical codes')
    trees = []
    fields = ['value', 'feature_idx', 'num_threshold', 'missing_go_to_left',
              'left', 'right', 'is_leaf', 'is_categorical', 'bitset_idx']
    for iteration in model._predictors:
        tree = iteration[0]
        nodes = [[n[f].item() for f in fields] for n in tree.nodes]
        # Infinity represents the numerical split separating missing values.
        for row in nodes:
            if not np.isfinite(row[2]):
                if row[2] != np.inf:
                    raise ValueError('Unsupported numerical threshold')
                row[2] = 'Infinity'
        trees.append({'nodes': nodes, 'categories': tree.raw_left_cat_bitsets.tolist()})
    return {'format': 'hgb-squared-v1', 'version': 1,
            'sha256': hashlib.sha256(api.MODEL_PATH.read_bytes()).hexdigest(),
            'features': api.FEATURES, 'input_order': cats + nums,
            'ordinal_categories': categories,
            'base': float(model._baseline_prediction[0, 0]), 'node_fields': fields,
            'trees': trees}


def export_runtime():
    # Obtain the literal public explanatory metadata without any network/model run.
    original = api.predict_profile
    try:
        api.predict_profile = lambda *args: ([], {}, [])
        meta = api.recommend({'date': '2025-01-01', 'origin': api.stations()[0]})['meta']
    finally:
        api.predict_profile = original
    for key in ('service_date', 'boarding_station', 'weather_source', 'min_stops', 'max_stops', 'max_walk_minutes'):
        meta.pop(key)
    return {'version': 1, 'stations': api.stations(), 'station_names': api.STATION_NAMES,
            'holidays': sorted(api.HOLIDAYS), 'change': api.CHANGE,
            'walk_min_per_km': api.WALK_MIN_PER_KM, 'meta': meta,
            'schedules': {v: api.schedule_file(v) for v in ('20250930', '20260330')},
            'pois': json.loads((ROOT / 'web/data/pois.json').read_text(encoding='utf-8'))}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')), encoding='utf-8')


def build(output):
    output = Path(output).resolve()
    source = ROOT / 'static_src'
    for name in ('index.html', 'app.js', 'static-engine.js'):
        if not (source / name).is_file():
            raise FileNotFoundError(f'Missing static UI/runtime: {source / name}')
    if output == ROOT or output in (ROOT / 'web', source):
        raise ValueError('Output must be a separate package directory')
    t04_assets = read_t04_assets()
    output.mkdir(parents=True, exist_ok=True)
    # Explicit allowlist: never inspect or copy config.local.js.
    for name in ('style.css', 'layout.js', 'weather-client.js', 'analysis.js'):
        shutil.copyfile(ROOT / 'web' / name, output / name)
    for name in ('metro_line_geometry.json', 'pois.json'):
        target = output / 'data' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / 'web/data' / name, target)
    for name in ('index.html', 'app.js', 'static-engine.js', 'style.css',
                 'map-view.js', 'map-view.css', 'map-config.js', 'map-projection.js',
                 't04-core.js', 't04-board.js', 't04-board.css'):
        if (source / name).is_file():
            shutil.copyfile(source / name, output / name)
    for name, content in t04_assets.items():
        target = output / 'data/t04' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    # These generated legacy files belong to the browser-key SDK integration.
    # The static site now obtains map images from a Worker and needs no app key.
    for name in ('kakao-loader.js', 'config.example.js'):
        legacy = output / name
        if legacy.is_file():
            legacy.unlink()
    write_json(output / 'data/model.json', export_model())
    write_json(output / 'data/runtime.json', export_runtime())
    weather = sorted((ROOT / 'data/raw/weather').glob('????-??-??.json'))
    for path in weather:
        hourly = json.loads(path.read_text(encoding='utf-8'))['hourly']
        write_json(output / 'data/weather' / path.name,
                   {'hourly': {k: hourly[k] for k in ('time', 'temperature_2m', 'precipitation', 'snowfall')}})
    print(f'Built {output}: {len(weather)} weather days; user config.local.js preserved')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'static-web')
    build(parser.parse_args().output)
