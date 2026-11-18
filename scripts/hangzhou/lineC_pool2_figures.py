"""Two Plotly figures for lineC_pool2 (system python)."""
import json
from pathlib import Path
import numpy as np, plotly.graph_objects as go
from plotly.subplots import make_subplots
R0 = Path(__file__).resolve().parents[2] / "outputs/hangzhou"
OUT = R0 / "lineC_pool2"
F = json.loads((OUT / "fig_data.json").read_text()); M = json.loads((OUT / "pool2_metrics.json").read_text(encoding="utf-8"))
P1 = json.loads((R0 / "lineC_pool/pool_metrics.json").read_text(encoding="utf-8"))
bins = np.arange(0, 24 * 3600 + 1, 600)
f = make_subplots(rows=2, cols=1, shared_xaxes=True, subplot_titles=("toward_34: 이전 풀링(기준 시각 T0, 10분당 열차 수)", "toward_34: pool2 (주황 = imputed)"))
f.add_trace(go.Bar(x=bins[:-1] / 3600, y=np.histogram(F["prev_pool"]["toward_34"], bins)[0], marker_color="#1f77b4", showlegend=False), row=1, col=1)
f.add_trace(go.Bar(x=bins[:-1] / 3600, y=np.histogram(F["pool2"]["toward_34"], bins)[0], marker_color="#1f77b4", name="관측 열차"), row=2, col=1)
f.add_trace(go.Bar(x=bins[:-1] / 3600, y=np.histogram(F["pool2_imputed"]["toward_34"], bins)[0], marker_color="#ff7f0e", name="imputed"), row=2, col=1)
f.update_layout(barmode="stack", template="plotly_white", height=560, xaxis2_title="시각(시)", title="아침 공백과 새벽 가짜 열차 (이전 vs pool2)")
f.write_html(OUT / "fig1_gaps_and_ghosts.html", include_plotlyjs="cdn")
cfg = {"1/08 단일일+랙": P1["ii_single0108_fitted_lags"], "이전 풀링+랙": M["pool_prev_rebuilt"]["fitted"]["all"], "pool2_centered": M["pool2_centered"]["fitted"]["all"],
       "pool2": M["pool2"]["fitted"]["all"], "대조 무작위 시간표": M["controls_refit_lags_25pct"]["random_timetable"], "대조 열차 섞기": M["controls_refit_lags_25pct"]["local_shuffle5"]}
g = make_subplots(rows=1, cols=3, subplot_titles=("배정 가능", "0~600초 창 안", "방향 일치율"))
for i, k in enumerate(("assignable", "window", "dir_match"), 1):
    g.add_trace(go.Bar(x=list(cfg), y=[v[k] for v in cfg.values()], showlegend=False, marker_color=["#999", "#999", "#bbb", "#1f77b4", "#d62728", "#d62728"]), row=1, col=i)
g.update_layout(template="plotly_white", height=440, title="설명 비율 비교 (음수 ~5%는 랙 맞춤의 구조적 결과라 제외)")
g.write_html(OUT / "fig2_explained_share.html", include_plotlyjs="cdn")
