import pandas as pd

for date in ['2026-10-02', '2026-10-15', '2026-10-31']:
    try:
        tables = pd.read_html(f'data/raw/bus/{date}.xls')
        df = tables[0]
        print(f'{date}: rows={len(df)}, routes={df["노선"].nunique()}, stops={df["정류장"].nunique()}, hours={df["시간"].nunique()}')
        print(f'  Time range: {sorted(df["시간"].unique())}')
    except Exception as e:
        print(f'{date}: ERROR - {e}')