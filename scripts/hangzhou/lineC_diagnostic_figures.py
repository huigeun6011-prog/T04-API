"""Render the 2019-01-08 C candidate diagnostics as offline figures (requires Plotly)."""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lineC_direct import load_direct_inputs
from lineC_route_gate import DATE, OUT
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from scipy.ndimage import gaussian_filter1d


def time_station_figure(events, stations):
    figure = go.Figure()
    styles = {"toward_34": ("34번 방향", "#15667d"), "toward_66": ("66번 방향", "#ae5027")}
    for direction, sample in events.groupby("direction"):
        name, color = styles[direction]
        track_x, track_y = [], []
        for _, group in sample.groupby("train_id"):
            track_x.extend([*group.arrival_time, None])
            track_y.extend([*group.stationID, None])
        figure.add_trace(go.Scattergl(x=track_x, y=track_y, mode="lines", name=f"{name} 연결",
                                     line=dict(color=color, width=1), opacity=0.45, hoverinfo="skip"))
        for kind, marker, size in (("observed", "circle", 4), ("imputed", "diamond-open", 7)):
            points = sample.loc[sample.observation.eq(kind)]
            label = "피크" if kind == "observed" else "보간"
            figure.add_trace(go.Scattergl(
                x=points.arrival_time, y=points.stationID, text=points.train_id, mode="markers",
                name=f"{name} {label}", marker=dict(color=color, symbol=marker, size=size), opacity=0.65,
                hovertemplate="%{x|%H:%M:%S} · %{y}번역<br>%{text}<extra></extra>",
            ))
    figure.update_layout(template="plotly_white", height=720, title="C선 도착 후보 시공도",
                         xaxis_title="1월 8일 현지 시각", yaxis_title="선로 순서와 역 ID",
                         margin=dict(l=70, r=45, t=60, b=70))
    figure.update_xaxes(tickformat="%H:%M", rangeslider_visible=True)
    figure.update_yaxes(tickvals=stations, ticktext=["54 (태그 없음)" if s == 54 else str(s) for s in stations])
    return figure


def example_station_figure(anchors, events):
    station, direction = 60, "toward_34"
    lo, hi = 10 * 3600, 11 * 3600
    midnight = pd.Timestamp(DATE)
    tags = anchors.loc[anchors.exit_station.eq(station) & anchors.direction.eq(direction), "exit_seconds"]
    histogram = np.bincount(tags, minlength=86_400)
    seconds = np.arange(lo, hi)
    timestamps = midnight + pd.to_timedelta(seconds, unit="s")
    smooth = gaussian_filter1d(histogram.astype(float), 10)
    detected = events.loc[events.stationID.eq(station) & events.direction.eq(direction)
                          & events.tag_peak_seconds.ge(lo) & events.tag_peak_seconds.lt(hi)]
    indices = detected.tag_peak_seconds.to_numpy(dtype=int)
    figure = go.Figure()
    figure.add_trace(go.Scatter(x=timestamps, y=histogram[lo:hi], mode="lines", line=dict(color="#c6cbd1", width=1),
                                name="초당 출장 태그"))
    figure.add_trace(go.Scatter(x=timestamps, y=smooth[lo:hi], mode="lines", line=dict(color="#15667d", width=2),
                                name="평활한 초당 태그"))
    figure.add_trace(go.Scatter(x=midnight + pd.to_timedelta(indices, unit="s"), y=smooth[indices],
                                mode="markers", marker=dict(color="#ae5027", symbol="diamond", size=8), name="검출 피크"))
    figure.add_trace(go.Scatter(x=detected.arrival_time, y=np.zeros(len(detected)), mode="markers",
                                marker=dict(color="#ae5027", symbol="triangle-up", size=9), name="도착 후보 시각"))
    figure.update_layout(template="plotly_white", height=460, title="60번역 · 34번 방향 · 10~11시",
                         xaxis_title="1월 8일 현지 시각", yaxis_title="초당 출장 태그 수", hovermode="x unified",
                         margin=dict(l=70, r=45, t=60, b=70))
    figure.update_xaxes(tickformat="%H:%M")
    return figure


def main():
    events = pd.read_csv(OUT / "candidate_arrival_events.csv", parse_dates=["arrival_time"])
    gate = json.loads((OUT / "fragmentation_result.json").read_text(encoding="utf-8"))
    corridor, _, anchors, _ = load_direct_inputs()
    chart = time_station_figure(events, corridor).to_html(full_html=False, include_plotlyjs=True)
    example = example_station_figure(anchors, events).to_html(full_html=False, include_plotlyjs=False)
    status = "통과" if gate["passed"] else "실패"
    html = f"""<!doctype html>
<html lang="ko">
<meta charset="utf-8">
<title>2019-01-08 항저우 C선 도착 후보 진단</title>
<body style="margin:2rem;font-family:system-ui,sans-serif;color:#182231">
<h1>2019-01-08 항저우 C선 도착 후보 진단</h1>
<p>조각화 관문 {status}. 점은 방향을 추정한 출장 태그 피크 또는 사이 역 보간에 기반한 도착 후보입니다.</p>
{chart}
{example}
</body>
</html>
"""
    (OUT / "diagnostic_figures.html").write_text(html, encoding="utf-8")


if __name__ == "__main__":
    main()
