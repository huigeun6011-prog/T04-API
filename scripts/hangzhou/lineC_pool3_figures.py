"""Two Plotly figures for lineC_pool3 (system python)."""
import json
from pathlib import Path
import numpy as np, plotly.graph_objects as go
from plotly.subplots import make_subplots
OUT = Path(__file__).resolve().parents[2] / "outputs/hangzhou/lineC_pool3"
F = json.loads((OUT / "fig_data.json").read_text()); M = json.loads((OUT / "pool3_metrics.json").read_text(encoding="utf-8"))
bins = np.arange(5 * 3600, 23.5 * 3600 + 1, 1800)
f = make_subplots(rows=1, cols=2, shared_yaxes=True, subplot_titles=("toward_34", "toward_66"))
for i, d in enumerate(("toward_34", "toward_66"), 1):
    for lab, c in (("pool2", "#999"), ("pool3", "#1f77b4")):
        f.add_trace(go.Bar(x=bins[:-1] / 3600, y=np.histogram(F[lab][d], bins)[0], name=lab, marker_color=c, showlegend=i == 1, opacity=0.8), row=1, col=i)
f.update_layout(barmode="overlay", template="plotly_white", height=380, title="30분당 열차 수 (pool2 vs pool3)", xaxis_title="시각(시)")
f.write_html(OUT / "fig1_trains_per_30min.html", include_plotlyjs="cdn")
S = M["headway_ratio_toward34_over_toward66"]; b = list(S["pool2"])
g = go.Figure([go.Bar(x=b, y=[S["pool2"][k] for k in b], name="pool2", marker_color="#999"), go.Bar(x=b, y=[S["pool3"][k] for k in b], name="pool3", marker_color="#1f77b4")])
g.add_hline(y=1.0, line_dash="dash"); g.update_layout(barmode="group", template="plotly_white", title="평균 배차 간격 비 (34번 방향 / 66번 방향), 1.0 = 대칭", height=380)
g.write_html(OUT / "fig2_headway_symmetry.html", include_plotlyjs="cdn")
