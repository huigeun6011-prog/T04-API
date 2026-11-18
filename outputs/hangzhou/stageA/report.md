# Stage A: is the Hangzhou tag data viable for timetable reconstruction? (2019-01-08 only)
Scripts: scripts/hangzhou/stageA_pairing.py, stageA_peaks.py, stageA_null_control.py (run in that order; single process, python -I). Visibility classes were declared in the header of stageA_peaks.py before any result was seen. 2019-01-15 and all other days were not opened.

## Short answer
- Visibility on exit peaks (10:00-16:00, 80 stations): **54 clear, 25 weak, 1 none**. Per line: A 11 clear / 3 weak / 0 none; B 19 / 14 / 1; C 24 / 8 / 0. The 54 clear stations hold 63% of the day's exits, the 25 weak ones about 30%, the one 'none' station (B/15, the busiest) 6.7%.
- Control: Poisson exits with the same slow rate and no arrival structure give 0 clear, 26 weak, 54 none with the same detector. So 'clear' is real structure; 'weak' (25 stations) is not distinguishable from the no-structure control and should be treated as unresolved without direction split.
- Direction split (hypothesis, see below) makes peaks clearer: B/15 goes from none to clear in both directions (70 and 66 peaks, explained 0.71 each), and 15 of 16 single-direction subsets of the 8 test stations are clear.
- Continue to stage B/C: yes for the clear stations, using paired-exit direction labels; line B (15 of 34 stations not clear, and the busiest ones) is the weak point and the busiest B stations (B/15, B/10) remain 'none' in the 07-09 rush window. Numbers only, no pass/fail threshold applied beyond the declared classes. Direction rests on the stationID-order hypothesis.

## 1. Pairing (exit paired with the same user's immediately preceding record being an entry on the same line, <= 180 min)
- 65.0% of exits paired, 65.1% of entries paired. By payType (exits): 0: 60.0%, 1: 64.1%, 2: 66.8%, 3: 70.7%. By line: A 25.3%, B 73.5%, C 64.7%.
- Why the rest is unpaired: the previous record is an entry on ANOTHER line for 25.9-40.0% of exits (by payType), previous record is an exit 0-0.7%, no previous record 0-2.4% (payType 3: 2.4%), gap > 180 min 0.6% for payType 3 only (exit_pairing_status_by_payType.csv).
- Pair travel minutes (same line): p05 6.7, median 19.6, p95 50.2, p99 65.7. payType 3: median 22.5, p95 58.4 (a bit longer, as expected if userID is not always one person).
## 2. Transfers
- There are no exit->entry transfer taps between lines: entries within 15 min after an exit of the same user are only 1.0% of entries and all are same-station re-entries (11,633); different-line 0, same-line-other-station 0. Gap hist in entry_after_exit_gap_hist.csv (different-line entries within 60 min of an exit total about 800, ~0.07% of entries).
- Instead, in-system transfers show as trips whose entry line differs from the exit line: 34.4% of all exits (entry_line_to_exit_line_trips.csv; biggest B<->C 8.7% each way, A<->B 5.6%, A<->C 2.9-3.0%). Their travel time is long (median 26-35 min, p10 13-19 min) against 18-21 min for same-line trips. So single-line pairing only contains trips that stayed on the line (paired exits whose entry follows another line's exit within 15 min: 0.0%), but about a third of exits (and 75% of A's) can not be assigned to a single line trip and need the OD data as is.
## 3. Peak visibility (stationID-line stations)
- Files: station_peak_visibility_10-16.csv (per station: exits per day, exits in window, peaks, median interval, regularity, explained, coverage, lift, class), station_peak_visibility_07-09_top10.csv, class_counts_per_line.csv, none_class_stations.csv, null_control_poisson.csv.
- Clear stations: median peak interval 287 s (4.8 min, both directions mixed).
- 'none' station (10-16): B/15 only (76,887 exits/day; 2 peaks in the window, explained 0.05).
- Busiest 10 stations in 07-09: 3 clear, 5 weak, 2 none (B/15 and B/10).
- Caution: lift is 2-2.6 almost everywhere because the 2.5x mean height rule itself selects high-rate seconds; use lift only relative to the control (control weak/none median lift 1.7).
## 4. Direction (HYPOTHESIS: sign of exit id minus entry id)
- Labelled share of exits: 64.3% overall; per station median 68%, 5th pct 23%, 95th pct 80% (low where many exits come from other lines or the station is a line end).
- 8 stations in direction_split_peak_visibility.csv. Busiest 3 (B/15, B/9, B/7): all direction subsets clear (B/15 each direction explained 0.71 vs 0.04 combined). Mid-volume 5 (A/73, C/48, C/42, B/19, C/57): 9 of 10 subsets clear (A/73 id-increasing weak), while their combined all-exits version was clear for 3 and weak for 2.
- Pooling the paired exits of both directions is not clearer (regularity worse, mostly weak): separation helps, not the paired subset itself.
## Not checked
- Other days, whether stationID order = geographic order or branches, device-level (gate) splitting, 07-09 beyond the top 10, peak shape/width, the time lag from arrival to tap, entry-side peaks, payType 3 user-sharing beyond the rates above, train reconstruction. Peak counts and classes depend on the declared detector settings; no tuning was done.
