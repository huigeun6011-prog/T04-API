# Feasibility bound diagnostic (19 matched peak cases; diagnosis only, nothing calibrated)
Source: scripts/data_prep/diagnose_feasibility_bound.py -> feasibility_bound.csv, summary.json.
- Hourly taps are per station, BOTH directions combined (data/processed/subway/<date>.json). No direction split exists.
- Loose bound (all upstream boardings, one train, no alighting): 4,715-7,997 vs actual 604-717. actual > loose in 0/19 (0/19 incl. own-station boardings). Bound is uninformative (actual = 8-14% of it).
- "Tight" net (boardings - alightings, both directions mixed) is not a valid one-direction bound; it is below actual in 8/19 (3/19 using best of adjacent hours), negative for 정부청사 cases. Do not read it as impossibility.
- Usable even-share reference: 0.5 * upstream boardings / trains of that direction in the peak hour (no alighting). Needed concentration factor actual/share: 1.20-2.58 (mean 1.88, median 1.81), 10/19 <=2, 0/19 >3; 1.2-1.3x for 상행 탄방 with only 6 trains/hr (1156), ~2.2-2.6x for 하행 용문/상행 갈마.
- 8/19 cases straddle an hour boundary; shifting all hours -1h gives loose 2.8k-5.9k, still >> actual.
Verdict: data does not show tap undercount (actual far below the loose bound); gap is more consistent with within-hour concentration / splitting (needs only ~1.2-2.6x even share), but this is not proven since direction split and alighting cannot be separated.
