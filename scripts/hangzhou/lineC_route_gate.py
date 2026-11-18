"""Evaluate the existing C timetable route gate on the corrected 2019-01-08 graph."""

import os

for variable in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[variable] = "1"

from collections import defaultdict, deque
from itertools import combinations
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/external/hangzhou"
OUT = ROOT / "outputs/hangzhou/lineC_graph"
DATE = "2019-01-08"
TRANSFER_MINUTES = 5.0
TARGETS = {"BC": 0.60, "AC": 0.80}
B0_BC = 0.5986


def read_tags():
    tags = pd.read_csv(
        SOURCE / f"record_{DATE}.csv",
        usecols=["time", "stationID", "lineID", "status", "userID"],
        dtype={"stationID": "int16", "lineID": "category", "status": "int8"},
        parse_dates=["time"],
    )
    observed = tags[["stationID", "lineID"]].drop_duplicates()
    if observed.stationID.duplicated().any():
        raise ValueError("Expected a single gate code per observed station ID")
    if set(observed.lineID) != set("ABC"):
        raise ValueError("Expected the three anonymized gate codes A, B and C")
    gate_line = dict(zip(observed.stationID, observed.lineID))

    tags = tags.sort_values(["userID", "time", "status"], kind="stable")
    duration = (tags.time - tags.time.shift()).dt.total_seconds() / 60
    seconds = (tags.time - pd.Timestamp(DATE)).dt.total_seconds().astype("int32")
    if not seconds.between(0, 86399).all():
        raise ValueError(f"Tag timestamps fall outside {DATE}")
    exits = tags.status.eq(0)
    paired = (
        exits & tags.status.shift().eq(1)
        & tags.userID.eq(tags.userID.shift()) & duration.gt(0) & duration.le(180)
    )
    trips = pd.DataFrame({
        "entry_station": tags.stationID.shift()[paired].astype("int16"),
        "exit_station": tags.stationID[paired],
        "exit_seconds": seconds[paired],
        "minutes": duration[paired],
    }).reset_index(drop=True)
    trips["entry_line"] = trips.entry_station.map(gate_line)
    trips["exit_line"] = trips.exit_station.map(gate_line)
    c_exits = exits & tags.lineID.eq("C")
    c_exits = pd.DataFrame({"stationID": tags.stationID[c_exits], "seconds": seconds[c_exits]})
    return gate_line, trips, c_exits


def build_topology(gate_line):
    adjacency = pd.read_csv(SOURCE / "Metro_roadMap.csv", index_col=0)
    ids = list(range(81))
    matrix = adjacency.to_numpy()
    if not (
        adjacency.index.tolist() == ids
        and adjacency.columns.astype(int).tolist() == ids
        and np.isin(matrix, [0, 1]).all()
        and np.array_equal(matrix, matrix.T)
        and not np.diag(matrix).any()
    ):
        raise ValueError("Expected a symmetric 81×81 binary matrix with matching station IDs")

    poi = pd.read_csv(SOURCE / "station_poi_data.csv", usecols=["stationID", "线路", "站点"])
    if set(poi.stationID) != set(ids):
        raise ValueError("POI IDs differ from the adjacency matrix IDs")
    poi["station_name"] = poi["站点"].str.replace(r"[A-Z]?站$", "", regex=True)
    poi_by_code = {code: set(rows.stationID) for code, rows in poi.groupby("线路")}
    gate_by_line = {line: {s for s in gate_line if gate_line[s] == line} for line in "ABC"}
    aliases = {}
    for line, gate_ids in gate_by_line.items():
        overlap = sorted((len(gate_ids & station_ids), code) for code, station_ids in poi_by_code.items())
        if overlap[-1][0] * 2 <= len(gate_ids) or overlap[-1][0] == overlap[-2][0]:
            raise ValueError(f"POI line is ambiguous for gate line {line}")
        aliases[line] = overlap[-1][1]
    if len(set(aliases.values())) != len(aliases):
        raise ValueError("Gate lines do not map uniquely to POI lines")

    nodes = {line: poi_by_code[aliases[line]] | gate_by_line[line] for line in "ABC"}
    membership = {s: tuple(line for line in nodes if s in nodes[line]) for s in ids}
    raw_neighbors = {s: set(np.flatnonzero(matrix[s]).tolist()) for s in ids}
    tracks = {line: {s: sorted(raw_neighbors[s] & stations) for s in sorted(stations)}
              for line, stations in nodes.items()}
    transfers = defaultdict(set)
    for _, station_ids in poi.groupby("station_name").stationID:
        states = sorted({(line, s) for s in station_ids for line in membership[s]})
        for (a_line, a), (b_line, b) in combinations(states, 2):
            if a_line != b_line and (a == b or raw_neighbors[a] == raw_neighbors[b]):
                transfers[(a_line, b_line)].add((a, b))
                transfers[(b_line, a_line)].add((b, a))
    if set(transfers) != {(a, b) for a in nodes for b in nodes if a != b}:
        raise ValueError("Could not identify transfers for every line pair")
    transfers = {key: sorted(value) for key, value in transfers.items()}

    names = poi.drop_duplicates("stationID").set_index("stationID").station_name
    station_rows = [
        {"line": line, "stationID": s, "name": names.at[s], "gate_line": gate_line.get(s, ""),
         "neighbors": ";".join(map(str, neighbors))}
        for line, stations in tracks.items() for s, neighbors in stations.items()
    ]
    track_edges = {tuple(sorted((s, n))) for stations in tracks.values() for s, ns in stations.items() for n in ns}
    raw_edges = {(i, j) for i in ids for j in raw_neighbors[i] if i < j}
    ignored_edges = sorted(raw_edges - track_edges)
    expanded_transfer_edges = set()
    for (_, b_line), connections in transfers.items():
        for a, b in connections:
            if a != b:
                expanded_transfer_edges.update(tuple(sorted((a, n))) for n in tracks[b_line][b])
    if not set(ignored_edges) <= expanded_transfer_edges:
        raise ValueError(f"Unexplained cross-line adjacency edges {ignored_edges}")
    return tracks, membership, transfers, pd.DataFrame(station_rows), ignored_edges


def graph_distances(tracks):
    distances = {}
    for line, neighbors in tracks.items():
        distances[line] = {}
        for start in neighbors:
            queue = deque([start])
            steps = {start: 0}
            while queue:
                station = queue.popleft()
                for next_station in neighbors[station]:
                    if next_station not in steps:
                        steps[next_station] = steps[station] + 1
                        queue.append(next_station)
            if len(steps) != len(neighbors):
                raise ValueError(f"Line {line} is disconnected")
            distances[line][start] = steps
    return distances


def corridor_order(neighbors):
    ends = [s for s, ns in neighbors.items() if len(ns) == 1]
    if len(ends) != 2 or any(len(ns) > 2 for ns in neighbors.values()):
        raise ValueError("Line C is not a single corridor")
    order = [min(ends)]
    prior = None
    while len(order) < len(neighbors):
        current = order[-1]
        order.append(next(s for s in neighbors[current] if s != prior))
        prior = current
    return order


def fit_legs(trips, membership, distances):
    models = {}
    ride = {}
    for line, hops in distances.items():
        stations = {s for s in hops if membership[s] == (line,)}
        sample = trips.loc[
            trips.entry_line.eq(line) & trips.exit_line.eq(line)
            & trips.entry_station.isin(stations) & trips.exit_station.isin(stations)
            & trips.entry_station.ne(trips.exit_station)
        ].copy()
        sample["hops"] = [hops[a][b] for a, b in zip(sample.entry_station, sample.exit_station)]
        by_hops = sample.groupby("hops").minutes.agg(n="size", q25=lambda x: x.quantile(0.25))
        by_hops = by_hops.loc[by_hops.n >= 30]
        steps = by_hops.index.to_numpy()
        low = np.maximum.accumulate(by_hops.q25.to_numpy())
        short = steps <= 8
        if len(steps[short]) < 2:
            raise ValueError(f"Insufficient valid short-hop trip data for {line}")
        slope, intercept = np.polyfit(steps[short], low[short], 1)
        all_steps = np.arange(1, max(max(d.values()) for d in hops.values()) + 1)
        extrapolation = np.maximum(all_steps - steps[-1], 0) * max(slope, 0.0)
        ride[line] = np.r_[0.0, np.maximum(np.interp(all_steps, steps, low) + extrapolation - intercept, 0.0)]
        models[line] = {
            "trips": len(sample), "intercept_min": float(intercept), "slope_min_per_hop": float(slope),
            "hop_counts": steps.tolist(), "monotone_q25_min": low.tolist(), "ride_min_by_hop": ride[line].tolist(),
        }
    return ride, models


def select_route(origin, destination, membership, transfers, distances, rides):
    def leg_time(line, a, b):
        return float(rides[line][distances[line][a][b]])

    def routes(line, station, used, segments, ride_minutes):
        if line in membership[destination]:
            final = segments + ((line, station, destination),)
            transfers_used = len(segments)
            total_ride = ride_minutes + leg_time(line, station, destination)
            yield total_ride + TRANSFER_MINUTES * transfers_used, transfers_used, final
        for next_line in sorted(set(distances) - used):
            for transfer_out, transfer_in in transfers.get((line, next_line), ()):
                yield from routes(
                    next_line, transfer_in, used | {next_line}, segments + ((line, station, transfer_out),),
                    ride_minutes + leg_time(line, station, transfer_out),
                )

    return min(route for start_line in membership[origin] for route in routes(start_line, origin, {start_line}, (), 0.0))


def evaluate(trips, membership, transfers, distances, rides):
    route_rows = []
    results = {}
    for pair, target in TARGETS.items():
        subset = trips.loc[trips.entry_line.isin(list(pair)) & trips.exit_line.isin(list(pair))
                           & trips.entry_line.ne(trips.exit_line)].copy()
        # The same route applies to all passengers of an OD pair, regardless of recorded travel time.
        od_routes = {}
        for (a, b), group in subset.groupby(["entry_station", "exit_station"], sort=True):
            cost, num_transfers, legs = select_route(a, b, membership, transfers, distances, rides)
            od_routes[(a, b)] = cost
            route_rows.append({
                "pair": pair, "entry_station": a, "exit_station": b, "trips": len(group),
                "transfer_count": num_transfers, "route": " ".join(f"{line}{s}-{line}{t}" for line, s, t in legs),
                "route_score_min": cost,
            })
        residual = subset.minutes.to_numpy() - np.array([
            od_routes[(a, b)] for a, b in zip(subset.entry_station, subset.exit_station)
        ])
        adjustment = float(np.median(residual))
        error = np.abs(residual - adjustment)
        within5 = float(np.mean(error <= 5.0))
        minimum = max(target, B0_BC - 0.03) if pair == "BC" else target
        results[pair] = {
            "trips": len(subset), "w_min": adjustment, "within_5_min": within5, "minimum": minimum,
            "mean_abs_min": float(error.mean()), "median_abs_min": float(np.median(error)),
            "passed": within5 >= minimum,
        }
    return results, pd.DataFrame(route_rows)


def main():
    gate_line, trips, _ = read_tags()
    tracks, membership, transfers, stations, ignored = build_topology(gate_line)
    distances = graph_distances(tracks)
    order = corridor_order(tracks["C"])
    rides, models = fit_legs(trips, membership, distances)
    results, routes = evaluate(trips, membership, transfers, distances, rides)
    passed = all(row["passed"] for row in results.values())
    data = {
        "date": DATE, "passed": passed, "transfer_minutes_for_route_choice": TRANSFER_MINUTES,
        "paired_trips": len(trips), "pairs": results, "leg_models": models, "corridor_order": order,
        "c_sites_without_tags": [s for s in order if s not in gate_line],
        "transfers": {"".join(pair): ts for pair, ts in transfers.items() if pair[0] < pair[1]},
        "matrix_edges_excluded_from_tracks": ignored,
    }

    OUT.mkdir(parents=True, exist_ok=True)
    stations.to_csv(OUT / "line_stations.csv", index=False, encoding="utf-8-sig")
    routes.to_csv(OUT / "routes_by_od.csv", index=False, float_format="%.6f")
    (OUT / "stage1_result.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(json.dumps({"date": DATE, "passed": passed, "pairs": results}, indent=2))


if __name__ == "__main__":
    main()
