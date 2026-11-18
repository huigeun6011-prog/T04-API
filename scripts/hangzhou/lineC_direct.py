"""Check direction anchors and arrival peak visibility from 2019-01-08 C-only trips."""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lineC_route_gate import DATE, OUT, build_topology, corridor_order, graph_distances, read_tags
import numpy as np
import pandas as pd
from peak_visibility import analyse


WINDOW = (10 * 3600, 16 * 3600)
MIN_DIRECTION_SHARE = 0.60
MIN_CLEAR_SHARE = 0.60


def direct_directions(trips, corridor, membership):
    position = dict(zip(corridor, range(len(corridor))))
    direct = trips.loc[
        trips.entry_line.eq("C") & trips.exit_line.eq("C") & trips.entry_station.ne(trips.exit_station)
    ].copy()
    direct["entry_position"] = direct.entry_station.map(position)
    direct["exit_position"] = direct.exit_station.map(position)
    if direct[["entry_position", "exit_position"]].isna().any().any():
        raise ValueError("Direct C trips contain stations outside the inferred C corridor")
    shared = {s for s in corridor if len(membership[s]) > 1}
    direct["direction"] = np.where(
        direct.exit_position.gt(direct.entry_position), f"toward_{corridor[-1]}", f"toward_{corridor[0]}"
    )
    direct["shared_endpoint"] = direct.entry_station.isin(shared) | direct.exit_station.isin(shared)
    return direct


def adjacent_times(anchors, active, corridor):
    position = dict(zip(corridor, range(len(corridor))))
    times = anchors.assign(
        lower=anchors[["entry_position", "exit_position"]].min(axis=1),
        upper=anchors[["entry_position", "exit_position"]].max(axis=1),
    ).groupby(["lower", "upper"]).minutes.agg(trips="size", q25_min=lambda t: t.quantile(0.25))
    rows = []
    for s, t in zip(active, active[1:]):
        a, b = position[s], position[t]
        result = times.loc[(a, b)].to_dict() if (a, b) in times.index else {"trips": 0, "q25_min": np.nan}
        rows.append({"station_from": s, "station_to": t, "graph_hops": b - a, **result})
    result = pd.DataFrame(rows)
    baseline = result.loc[result.trips.ge(30) & result.graph_hops.eq(1), "q25_min"].median()
    result["anomaly"] = np.where(
        result.trips.lt(30), "insufficient_trips",
        np.where(result.q25_min.lt(0.4 * baseline) | result.q25_min.gt(1.8 * baseline), "outlier", "")
    )
    return result


def direction_visibility(anchors, all_exits, active, corridor):
    lo, hi = WINDOW
    candidates = {
        (s, d): group.exit_seconds.to_numpy()
        for (s, d), group in anchors.groupby(["exit_station", "direction"])
    }
    direction_names = [f"toward_{corridor[0]}", f"toward_{corridor[-1]}"]
    visibility = pd.DataFrame([
        {"stationID": s, "direction": d, **analyse(candidates.get((s, d), np.empty(0, dtype=int)), lo, hi)}
        for s in active for d in direction_names
    ])
    window_exits = all_exits.loc[all_exits.seconds.ge(lo) & all_exits.seconds.lt(hi)]
    window_anchors = anchors.loc[anchors.exit_seconds.ge(lo) & anchors.exit_seconds.lt(hi)]
    clear_exits = int(visibility.loc[visibility.cls.eq("clear"), "exits_window"].sum())
    clear_share = clear_exits / len(window_exits)
    direction_share = len(anchors) / len(all_exits)
    sensitivity = anchors.loc[~anchors.shared_endpoint]
    result = {
        "date": DATE,
        "corridor_order": corridor,
        "c_exits_day": len(all_exits),
        "direct_direction_exits_day": len(anchors),
        "direct_direction_share": direction_share,
        "direct_direction_minimum": MIN_DIRECTION_SHARE,
        "direct_direction_passed": direction_share >= MIN_DIRECTION_SHARE,
        "shared_endpoint_directions": int(anchors.shared_endpoint.sum()),
        "direct_direction_share_without_shared_endpoints": len(sensitivity) / len(all_exits),
        "c_exits_10_16": len(window_exits),
        "direct_direction_exits_10_16": len(window_anchors),
        "direct_direction_share_10_16": len(window_anchors) / len(window_exits),
        "clear_cell_direction_exits_10_16": clear_exits,
        "clear_cell_share_of_direction_exits_10_16": clear_exits / len(window_anchors),
        "clear_cell_share_of_all_exits_10_16": clear_share,
        "clear_cell_minimum": MIN_CLEAR_SHARE,
        "clear_cell_passed": clear_share >= MIN_CLEAR_SHARE,
        "cells_by_visibility": visibility.cls.value_counts().to_dict(),
    }
    return visibility, result


def load_direct_inputs():
    gate_line, trips, all_exits = read_tags()
    tracks, membership, _, _, _ = build_topology(gate_line)
    graph_distances({"C": tracks["C"]})
    corridor = corridor_order(tracks["C"])
    active = [s for s in corridor if gate_line.get(s) == "C"]
    anchors = direct_directions(trips, corridor, membership)
    return corridor, active, anchors, all_exits


def main():
    corridor, active, anchors, all_exits = load_direct_inputs()
    visibility, result = direction_visibility(anchors, all_exits, active, corridor)
    result["passed"] = result["direct_direction_passed"] and result["clear_cell_passed"]
    OUT.mkdir(parents=True, exist_ok=True)
    adjacent_times(anchors, active, corridor).to_csv(OUT / "c_adjacent_direct_trips.csv", index=False)
    visibility.to_csv(OUT / "c_direction_peak_visibility_10_16.csv", index=False, float_format="%.6f")
    (OUT / "direct_peak_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
