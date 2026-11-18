"""Figure for lineC_pos (system python): detection rate by planted fraction and turn position."""
from pathlib import Path
import pandas as pd, plotly.graph_objects as go
from plotly.subplots import make_subplots
OUT = Path(__file__).resolve().parents[2] / "outputs/hangzhou/lineC_pos"
D = pd.read_csv(OUT / "detection_by_scenario.csv")
cols = [("det_E1_reduced", "E1 reduced"), ("det_E3_absent_ge_015", "E3 absent>=0.15"), ("det_E2_supportive_at_turn_segment", "E2 (V1만)"), ("det_synthesis_informative", "종합 지원")]
fig = make_subplots(rows=1, cols=2, shared_yaxes=True, subplot_titles=("V0 제거", "V1 제거+회차 하차 이동"))
for j, v in enumerate((0, 1), 1):
    for c, n in cols:
        for p in (13, 18, 23):
            x = D[(D.variant == v) & (D.p == p)]
            fig.add_trace(go.Scatter(x=x.f, y=x[c], mode="lines+markers", name=f"{n} p{p}", legendgroup=n, showlegend=j == 1), row=1, col=j)
fig.add_hline(y=0.7, line_dash="dash", annotation_text="신뢰 기준 0.70")
fig.update_layout(template="plotly_white", height=460, title="양성 대조: 심은 단축 비율 f별 검출률", xaxis_title="심은 열차 비율 f", yaxis_range=[-0.05, 1.05])
fig.write_html(OUT / "fig1_detection.html", include_plotlyjs="cdn")
