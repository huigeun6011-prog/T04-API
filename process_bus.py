import pandas as pd
import json
import re
from pathlib import Path

def parse_stop(stop_str):
    match = re.match(r'^(.+?)\((\d+)\)$', str(stop_str))
    if match:
        return match.group(1), match.group(2)
    return str(stop_str), ""

def parse_route(route_str):
    match = re.match(r'^([^(]+)', str(route_str))
    if match:
        return match.group(1).strip()
    return str(route_str).strip()

def parse_date(date_str):
    match = re.search(r'(\d{4})년 (\d{1,2})월 (\d{1,2})일', str(date_str))
    if match:
        return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    return str(date_str)

def parse_time(time_str):
    match = re.match(r'(\d{1,2}):', str(time_str))
    if match:
        return int(match.group(1))
    return 0

def process_file(input_path, output_dir):
    dfs = pd.read_html(input_path)
    df = dfs[0].copy()

    df.columns = ['date', 'route', 'time', 'seq', 'stop', 'boarding', 'alighting', 'transfer']

    df['date'] = df['date'].ffill()
    df['route'] = df['route'].ffill()
    df = df[~df['route'].str.contains('합계')].copy()
    df['time'] = df['time'].ffill()

    df['boarding'] = df['boarding'].fillna(0).astype(int)
    df['alighting'] = df['alighting'].fillna(0).astype(int)
    df['transfer'] = df['transfer'].fillna(0).astype(int)
    df = df[df['seq'].apply(lambda x: str(x).isdigit())].copy()
    df['seq'] = df['seq'].astype(int)

    df['date_parsed'] = df['date'].apply(parse_date)
    df['route_id'] = df['route'].apply(parse_route)
    df['time_hour'] = df['time'].apply(parse_time)
    df[['stop_name', 'stop_id']] = df['stop'].apply(lambda x: pd.Series(parse_stop(x)))

    routes = df.groupby('route_id')

    for route_name, group in routes:
        date_str = group['date_parsed'].iloc[0]

        stops = group.drop_duplicates(subset='seq').sort_values('seq')[
            ['seq', 'stop_name', 'stop_id']
        ].to_dict('records')
        stops = [{'seq': int(r['seq']), 'name': r['stop_name'], 'id': r['stop_id']} for r in stops]

        hourly_records = []
        for hour in sorted(group['time_hour'].unique()):
            hour_group = group[group['time_hour'] == hour].sort_values('seq')
            data = hour_group[['seq', 'boarding', 'alighting', 'transfer']].to_dict('records')
            data = [{'seq': int(r['seq']), 'boardings': int(r['boarding']),
                     'alightings': int(r['alighting']), 'transfers': int(r['transfer'])} for r in data]
            hourly_records.append({'time': int(hour), 'data': data})

        result = {
            'date': date_str,
            'route': route_name,
            'stops': stops,
            'hourly_records': hourly_records
        }

        output_path = output_dir / f"{route_name}_{date_str}.json"
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"Saved: {output_path}")

if __name__ == '__main__':
    input_file = Path('data/raw/bus/2026-10-23.xls')
    output_dir = Path('data/processed/bus')
    process_file(input_file, output_dir)