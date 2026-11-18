"""Link C arrival candidates on 2019-01-08 and enforce the predeclared fragmentation gate."""

from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lineC_direct import direction_visibility, load_direct_inputs
from lineC_route_gate import DATE, OUT
import numpy as np
import pandas as pd
from scipy.ndimage import gaussian_filter1d, uniform_filter1d
from scipy.optimize import lsq_linear
from scipy.signal import find_peaks, peak_widths


SECONDS_PER_DAY = 86_400
WALK_SECONDS = 30
COARSE_TOLERANCE = 120
TOLERANCE = 45
MIN_BOTH_ENDS = 0.60
MAX_SMALL = 0.05


def find_daily_peaks(anchors, stations):
    by_station = {s: group.exit_seconds.to_numpy() for s, group in anchors.groupby("exit_station")}
    window = 2 * 30 * 60 + 1
    normalization = uniform_filter1d(np.ones(SECONDS_PER_DAY), window, mode="constant")
    outputs = []
    excluded_at_boundary = 0
    for station in stations:
        exit_times = by_station.get(station, np.empty(0, dtype=int))
        hist = np.bincount(exit_times, minlength=SECONDS_PER_DAY)
        smooth = gaussian_filter1d(hist.astype(float), 10)
        baseline = uniform_filter1d(smooth, window, mode="constant") / normalization
        indexes, properties = find_peaks(smooth, distance=45, height=2.5 * baseline, prominence=(None, None))
        widths, _, left, _ = peak_widths(
            smooth, indexes, prominence_data=(properties["prominences"], properties["left_bases"], properties["right_bases"])
        )
        arrival = left - WALK_SECONDS
        valid = (arrival >= 0) & (arrival < SECONDS_PER_DAY)
        cumulative_exits = np.r_[0, np.cumsum(hist)]
        support = cumulative_exits[np.minimum(indexes + 46, SECONDS_PER_DAY)] - cumulative_exits[np.maximum(indexes - 45, 0)]
        peaks = pd.DataFrame({
            "arrival_seconds": arrival[valid], "tag_peak_seconds": indexes[valid],
            "peak_strength": smooth[indexes[valid]] / baseline[indexes[valid]],
            "peak_prominence_tags_per_second": properties["prominences"][valid],
            "peak_width_seconds": widths[valid], "nearby_direction_tags": support[valid],
        }).sort_values("arrival_seconds", kind="stable").reset_index(drop=True)
        outputs.append(peaks)
        excluded_at_boundary += int((~valid).sum())
    return outputs, excluded_at_boundary


def initial_intervals(anchors, stations):
    od = anchors.groupby(["entry_station", "exit_station"]).minutes.agg(
        count="size", q25=lambda values: values.quantile(0.25)
    )
    od = od.loc[od["count"].ge(30)]
    positions = {s: i for i, s in enumerate(stations)}
    design = np.zeros((len(od), len(stations)))
    design[:, 0] = 1
    for row, (origin, destination) in enumerate(od.index):
        start, stop = positions[origin], positions[destination]
        design[row, start + 1:stop + 1] = 1
    weights = np.sqrt(od["count"].to_numpy())
    lower = np.r_[0.0, np.full(len(stations) - 1, 30.0)]
    result = lsq_linear(design * weights[:, None], od.q25.to_numpy() * 60 * weights, bounds=(lower, np.inf))
    if not result.success:
        raise ValueError(f"Could not fit initial interval times: {result.message}")
    return result.x[1:], float(result.x[0]), len(od)


def residuals(left, right, expected, tolerance):
    elapsed = right[None, :] - left[:, None]
    error = np.abs(elapsed - expected)
    error[(elapsed <= 0) | (error > tolerance)] = np.inf
    return error


def ordered_match(error, tolerance):
    """Find the largest order-preserving matching, then minimize total timing error."""
    n, m = error.shape
    reward = (min(n, m) + 1) * (tolerance + 1)
    move = np.zeros((n + 1, m + 1), dtype=np.uint8)
    previous = np.zeros(m + 1)
    for i in range(1, n + 1):
        current = np.zeros(m + 1)
        for j in range(1, m + 1):
            up, left = previous[j], current[j - 1]
            diagonal = previous[j - 1] + reward - error[i - 1, j - 1]
            if diagonal >= max(up, left):
                current[j], move[i, j] = diagonal, 2
            elif left > up:
                current[j], move[i, j] = left, 1
            else:
                current[j] = up
        previous = current
    matched = []
    i, j = n, m
    while i and j:
        action = move[i, j]
        if action == 2:
            matched.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif action == 1:
            j -= 1
        else:
            i -= 1
    return matched[::-1]


def calibrate_intervals(times, initial):
    calibrated = []
    counts = []
    for left, right, expected in zip(times, times[1:], initial):
        error = residuals(left, right, expected, COARSE_TOLERANCE)
        pairs = ordered_match(error, COARSE_TOLERANCE)
        calibrated.append(float(np.median([right[j] - left[i] for i, j in pairs])) if pairs else expected)
        counts.append(len(pairs))
    return np.asarray(calibrated), counts


def interpolate(times, cumulative, first, last):
    a, i = first
    b, j = last
    relative = (cumulative[a:b + 1] - cumulative[a]) / (cumulative[b] - cumulative[a])
    return times[a][i] + (times[b][j] - times[a][i]) * relative


def link_peaks(times, intervals):
    cumulative = np.r_[0, np.cumsum(intervals)]
    links = {}
    starts_with_previous = set()
    edges = [[] for _ in intervals]
    adjacent = {}
    for span in (1, 2, 3):
        for a in range(len(times) - span):
            b = a + span
            left = [i for i in range(len(times[a])) if (a, i) not in links]
            right = [i for i in range(len(times[b])) if (b, i) not in starts_with_previous]
            error = residuals(times[a][left], times[b][right], cumulative[b] - cumulative[a], TOLERANCE)
            if span > 1:
                occupied = [np.asarray(edges[pos]).reshape(-1, 2) for pos in range(a, b)]
                for i, j in np.argwhere(np.isfinite(error)):
                    proposal = interpolate(times, cumulative, (a, left[i]), (b, right[j]))
                    if any(np.any(np.prod(proposal[k:k + 2] - other, axis=1) <= 0)
                           for k, other in enumerate(occupied)):
                        error[i, j] = np.inf
            for i, j in ordered_match(error, TOLERANCE):
                first, last = (a, left[i]), (b, right[j])
                links[first] = last
                starts_with_previous.add(last)
                points = interpolate(times, cumulative, first, last)
                for k in range(span):
                    edges[a + k].append(points[k:k + 2])
        if span == 1:
            adjacent = links.copy()
    return adjacent, links


def split_tracks(times, links):
    nodes = {(s, i) for s, peaks in enumerate(times) for i in range(len(peaks))}
    starts = nodes - set(links.values())
    ordered_starts = sorted(starts, key=lambda node: (times[node[0]][node[1]], node))
    tracks = []
    for node in ordered_starts:
        track = [node]
        while node in links:
            node = links[node]
            track.append(node)
        tracks.append(track)
    if sum(map(len, tracks)) != len(nodes) or len(set(links.values())) != len(links):
        raise ValueError("Linking did not cover every candidate peak exactly once")
    return tracks


def record_tracks(tracks, direction, stations, peaks, times, intervals, mode):
    cumulative = np.r_[0, np.cumsum(intervals)]
    train_rows, event_rows = [], []
    for n, track in enumerate(tracks, 1):
        train_id = f"C-{DATE.replace('-', '')}-{direction}-{n:04d}"
        start, end = track[0][0], track[-1][0]
        connected = end - start + 1 if mode == "with_imputed" else len(track)
        train_rows.append({
            "mode": mode, "train_id": train_id, "direction": direction,
            "observed_stations": len(track), "connected_stations": connected,
            "imputed_stations": connected - len(track), "start_station": stations[start], "end_station": stations[end],
            "start_stations_from_terminal": start, "end_stations_from_terminal": len(stations) - 1 - end,
        })
        if mode != "with_imputed":
            continue
        for k, (s, p) in enumerate(track):
            if k:
                prev = track[k - 1]
                calculated = interpolate(times, cumulative, prev, (s, p))
                for index, seconds in enumerate(calculated[1:-1], prev[0] + 1):
                    event_rows.append({"train_id": train_id, "direction": direction, "stationID": stations[index],
                                       "imputed": True, "observation": "imputed", "arrival_seconds": seconds})
            event_rows.append({"train_id": train_id, "direction": direction, "stationID": stations[s],
                               "imputed": False, "observation": "observed", **peaks[s].iloc[p].to_dict()})
    return train_rows, event_rows


def describe_fragmentation(diagnostics):
    results = {}
    for mode, samples in diagnostics.groupby("mode"):
        by_dir = dict(tuple(samples.groupby("direction")))
        by_dir["pooled"] = samples
        results[mode] = {}
        for direction, rows in by_dir.items():
            start_near = rows.start_stations_from_terminal.le(2)
            end_near = rows.end_stations_from_terminal.le(2)
            results[mode][direction] = {
                "train_candidates": len(rows),
                "start_within_2_share": float(start_near.mean()), "end_within_2_share": float(end_near.mean()),
                "both_ends_within_2_share": float((start_near & end_near).mean()),
                "middle_start_share": float((~start_near).mean()), "middle_end_share": float((~end_near).mean()),
                "small_1_2_observed_share": float(rows.observed_stations.le(2).mean()),
                "small_1_2_connected_share": float(rows.connected_stations.le(2).mean()),
                "observed_events": int(rows.observed_stations.sum()), "imputed_events": int(rows.imputed_stations.sum()),
                "imputed_share": float(rows.imputed_stations.sum() / rows.connected_stations.sum()),
                "observed_station_count": dict(sorted(Counter(rows.observed_stations).items())),
                "connected_station_count": dict(sorted(Counter(rows.connected_stations).items())),
                "start_station_count": dict(sorted(Counter(rows.start_station).items())),
                "end_station_count": dict(sorted(Counter(rows.end_station).items())),
            }
    return results


def main():
    corridor, active, anchors, all_exits = load_direct_inputs()
    _, eligibility = direction_visibility(anchors, all_exits, active, corridor)
    if not (eligibility["direct_direction_passed"] and eligibility["clear_cell_passed"]):
        raise SystemExit("C-only direction or peak visibility gate failed. Trajectories were not computed.")

    rows, arrivals, fit_rows = [], [], []
    boundary = {}
    for stations in (active, active[::-1]):
        direction = f"toward_{stations[-1]}"
        sample = anchors.loc[anchors.direction.eq(direction)]
        peaks, boundary[direction] = find_daily_peaks(sample, stations)
        times = [stop.arrival_seconds.to_numpy() for stop in peaks]
        initial, intercept, od_count = initial_intervals(sample, stations)
        intervals, coarse_counts = calibrate_intervals(times, initial)
        adjacent, links = link_peaks(times, intervals)
        adjacent_only = split_tracks(times, adjacent)
        full = split_tracks(times, links)
        for mode, tracks in (("adjacent_observed", adjacent_only), ("observed", full), ("with_imputed", full)):
            trains, events = record_tracks(tracks, direction, stations, peaks, times, intervals, mode)
            rows.extend(trains)
            arrivals.extend(events)
        fit_rows.extend({
            "direction": direction, "from_station": a, "to_station": b, "initial_seconds": before,
            "calibrated_seconds": after, "coarse_matches": count, "fit_intercept_seconds": intercept, "fit_ods": od_count,
        } for a, b, before, after, count in zip(stations, stations[1:], initial, intervals, coarse_counts))

    diagnostics = pd.DataFrame(rows)
    events = pd.DataFrame(arrivals)
    fragmentation = describe_fragmentation(diagnostics)
    central = fragmentation["observed"]["pooled"]
    passed = (central["both_ends_within_2_share"] >= MIN_BOTH_ENDS
              and central["small_1_2_observed_share"] <= MAX_SMALL)
    events["arrival_time"] = pd.Timestamp(DATE) + pd.to_timedelta(events.arrival_seconds.round(), unit="s")
    if not events.sort_values("arrival_seconds").groupby("train_id").arrival_time.apply(lambda ts: ts.is_unique).all():
        raise ValueError("A candidate has multiple arrivals at the same second")
    events["quality_gate"] = "passed" if passed else "failed_fragmentation"
    event_columns = ["train_id", "direction", "stationID", "arrival_time", "observation", "imputed", "peak_strength",
                     "tag_peak_seconds", "peak_prominence_tags_per_second", "peak_width_seconds", "nearby_direction_tags",
                     "quality_gate"]
    result = {
        "date": DATE, "passed": passed, "both_ends_within_2_minimum": MIN_BOTH_ENDS,
        "small_1_2_observed_maximum": MAX_SMALL, "peaks_excluded_by_date_boundary": boundary,
        "fragmentation": fragmentation,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "fragmentation_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    diagnostics.to_csv(OUT / "train_candidate_fragmentation.csv", index=False)
    pd.DataFrame(fit_rows).to_csv(OUT / "c_interval_fit.csv", index=False, float_format="%.3f")
    events.groupby(["direction", "stationID"], as_index=False).imputed.agg(
        events="size", imputed_events="sum", imputed_share="mean"
    ).to_csv(OUT / "c_imputation_by_station.csv", index=False, float_format="%.6f")
    events.to_csv(OUT / "candidate_arrival_events.csv", columns=event_columns, index=False, float_format="%.6f")
    if passed:
        events.to_csv(OUT / "arrivals.csv", columns=event_columns, index=False, float_format="%.6f")
    print(json.dumps({"date": DATE, "passed": passed, "boundary_exclusions": boundary, "observed": central}, indent=2))


if __name__ == "__main__":
    main()
