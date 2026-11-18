"""Two Plotly figures for lineC_struct (system python)."""
from pathlib import Path
import numpy as np, pandas as pd, plotly.graph_objects as go
from plotly.subplots import make_subplots
OUT = Path(__file__).resolve().parents[2] / "outputs/hangzhou/lineC_struct"
E = pd.read_csv(OUT / "e1_headway_by_station.csv"); S = pd.read_csv(OUT / "synthesis_by_segment.csv")
bands = ["05-07", "07-09", "09-17", "17-19", "19-23:30"]
f = make_subplots(rows=1, cols=2, subplot_titles=("toward_34 (66쪽 출발 순서)", "toward_66 (34쪽 출발 순서)"), shared_yaxes=True)
for i, d in enumerate(("toward_34", "toward_66"), 1):
    z = np.full((5, 32), np.nan)
    for b, bn in enumerate(bands):
        x = E[(E.direction == d) & (E.band == bn)].sort_values("pos")
        z[b] = np.where(x.informative, x.headway_s, np.nan)
    f.add_trace(go.Heatmap(z=z, x=list(range(32)), y=bands, zmin=200, zmax=500, colorscale="Viridis", showscale=i == 2, colorbar=dict(title="간격(초)")), row=1, col=i)
f.update_layout(template="plotly_white", height=380, title="독립 하차 피크 평균 간격 (정보 있는 칸만, 빈 칸 = 알 수 없음). 가로 = 방향 진행 순서의 역 위치")
f.write_html(OUT / "fig1_headway_heatmap.html", include_plotlyjs="cdn")
g = make_subplots(rows=1, cols=2, subplot_titles=("E3 absent 비율(그 구간에 안 간 것으로 보이는 열차)", "E3 present 비율"), shared_yaxes=True)
for i, col in enumerate(("e3_absent", "e3_present"), 1):
    for d, c in (("toward_34", "#1f77b4"), ("toward_66", "#ff7f0e")):
        for b, bn in enumerate(bands):
            x = S[(S.direction == d) & (S.band == bn)]
            g.add_trace(go.Scatter(x=x.seg, y=x[col], mode="lines+markers", name=f"{d} {bn}", legendgroup=d, line=dict(color=c, width=1 + (bn in ("07-09", "17-19"))),
                                   opacity=1 if bn in ("07-09", "17-19") else 0.35, showlegend=i == 1), row=1, col=i)
g.update_layout(template="plotly_white", height=420, title="승객 단위 구간 도달 (구간 0 = 출발 종점쪽, 5 = 도착 종점쪽)")
g.write_html(OUT / "fig2_e3_segment_reach.html", include_plotlyjs="cdn")
