"""Two Plotly figures for lineC_pool (system python)."""
import json
from pathlib import Path
import pandas as pd, plotly.graph_objects as go
from plotly.subplots import make_subplots
OUT = Path(__file__).resolve().parents[2] / "outputs/hangzhou/lineC_pool"
R = json.loads((OUT / "pool_metrics.json").read_text(encoding="utf-8"))
W = R["weekday"]
cfg = {"(i) 이전 1/08, 랙 30/0": R["i_old_a_0108_lag30_0"], "(ii) 1/08 단일일+랙 맞춤": R["ii_single0108_fitted_lags"],
       "(iii) 평일 풀링, 랙 30/0": W["iii_pooled_lag30_0"]["all"], "(iv) 평일 풀링+랙 맞춤": W["iv_pooled_fitted_lags"]["all"],
       "대조 무작위 시간표(랙 재맞춤)": W["controls_refit_lags_25pct_sample"]["random_timetable"],
       "대조 열차 섞기(랙 재맞춤)": W["controls_refit_lags_25pct_sample"]["local_shuffle5"]}
f = make_subplots(rows=1, cols=3, subplot_titles=("음수 대기", "0~600초 창 안", "방향 일치율"))
for i, k in enumerate(("neg", "window", "dir_match"), 1):
    f.add_trace(go.Bar(x=list(cfg), y=[v[k] for v in cfg.values()], showlegend=False, marker_color=["#999", "#bbb", "#999", "#1f77b4", "#d62728", "#d62728"]), row=1, col=i)
f.update_layout(title="승객 설명 비율 (이전 정의 동일). 음수 대기 ~5%는 랙 맞춤의 구조적 결과", template="plotly_white", height=460)
f.write_html(OUT / "fig1_explained_share.html", include_plotlyjs="cdn")
L = pd.read_csv(OUT / "lags_by_station.csv"); L = L[L.group == "weekday"]
g = make_subplots(rows=1, cols=2, subplot_titles=("하차 랙 L_out(초, 도착 기준)", "입장 랙 L_in(초)"))
for j, kind in enumerate(("out", "in"), 1):
    for d, c in (("toward_66", "#1f77b4"), ("toward_34", "#ff7f0e")):
        x = L[(L.kind == kind) & (L.direction == d)]
        g.add_trace(go.Scatter(x=x.stationID, y=x.lag_s, mode="lines+markers", name=d, line_color=c, showlegend=j == 1), row=1, col=j)
    g.add_hline(y=-30 if kind == "out" else 60, line_dash="dash", annotation_text="−60초 이동의 등가값", row=1, col=j)
g.update_layout(title="평일 그룹 역·방향별 랙 (수축 후)", template="plotly_white", height=420)
g.write_html(OUT / "fig2_lags_by_station.html", include_plotlyjs="cdn")
