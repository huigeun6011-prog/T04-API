"""Plotly figures for lineC_stack.py (run with the system python that has Plotly). Output: outputs/hangzhou/lineC_stack/figures.html"""
import json
from pathlib import Path
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

OUT = Path(__file__).resolve().parents[2] / "outputs/hangzhou/lineC_stack"
fd = json.loads((OUT / "fig_data.json").read_text(encoding="utf-8"))
dirs = [k for k in fd if k.startswith("toward")]
fig = make_subplots(rows=3, cols=2, subplot_titles=[f"{d}: 10-11h stack trains" for d in dirs] + [f"{d}: observed stations per train" for d in dirs] + ["headway (s)", "holdout recall by hidden station"], vertical_spacing=.12)
for c, d in enumerate(dirs, 1):
    f = fd[d]
    for a, o in zip(f["arr_10_11"], f["obs_10_11"]):
        a, o = np.array(a), np.array(o)
        fig.add_trace(go.Scatter(x=a / 3600, y=list(range(len(a))), mode="lines", line=dict(width=.7, color="#15667d"), showlegend=False, hoverinfo="skip"), 1, c)
        fig.add_trace(go.Scatter(x=a[o] / 3600, y=np.where(o)[0], mode="markers", marker=dict(size=4, color="#c0392b"), showlegend=False, hoverinfo="skip"), 1, c)
    px = [(t / 3600, k) for k, s in enumerate(f["stations"]) for t in f["peaks"].get(str(s), []) if 10 * 3600 <= t <= 11.2 * 3600]
    fig.add_trace(go.Scatter(x=[p[0] for p in px], y=[p[1] for p in px], mode="markers", marker=dict(size=5, color="black", symbol="x"), name="detected peak", showlegend=(c == 1)), 1, c)
    fig.update_xaxes(range=[10, 11.2], title_text="hour", row=1, col=c)
    fig.add_trace(go.Histogram(x=f["n_obs"], xbins=dict(start=-.5, end=len(f["stations"]) + .5, size=1), marker_color="#15667d", showlegend=False), 2, c)
    r = np.sort(f["refs"])
    fig.add_trace(go.Scatter(x=r[1:] / 3600, y=np.diff(r), mode="markers", marker=dict(size=3), name=d), 3, 1)
h = fd["holdout"]
fig.add_trace(go.Bar(x=[str(s) for s in h["stationID"]], y=h["recall"], name="hidden recall"), 3, 2)
fig.add_trace(go.Bar(x=[str(s) for s in h["stationID"]], y=h["recall_ctrl_mean"], name="shifted control"), 3, 2)
fig.update_yaxes(range=[0, 1500], row=3, col=1)
fig.update_layout(height=1100, width=1300, title="C line shift-and-stack (2019-01-08, same-day consistency)")
fig.write_html(OUT / "figures.html", include_plotlyjs="cdn")
