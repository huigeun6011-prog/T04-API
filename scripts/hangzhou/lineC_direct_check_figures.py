"""Two Plotly figures for lineC_direct_check (system python). Reads outputs/hangzhou/lineC_direct_check/{fig_data,direct_check_result}.json."""
import json
from pathlib import Path
import plotly.graph_objects as go
from plotly.subplots import make_subplots

OUT = Path(__file__).resolve().parents[2] / "outputs/hangzhou/lineC_direct_check"
F = json.loads((OUT / "fig_data.json").read_text(encoding="utf-8"))
R = json.loads((OUT / "direct_check_result.json").read_text(encoding="utf-8"))
mid = [b + 15 for b in F["bins"][:-1]]
names = {"baseline": "현재 시간표(a)", "shift-60s": "(a) −60초 이동(사후)", "local_shuffle5": "대조: 열차 국소 섞기",
         "random_timetable": "대조: 무작위 시간표", "direction_swap": "대조: 방향 뒤바꿈"}
fig = go.Figure()
for k, n in names.items():
    h = F[k]; tot = sum(h)
    fig.add_trace(go.Scatter(x=mid, y=[v / tot for v in h], mode="lines", name=n, line=dict(width=3 if k == "baseline" else 1.5)))
fig.add_vline(x=0, line_dash="dash")
fig.update_layout(title="입장 태그 후 대기시간 분포 (열차 출발 − 입장 태그, 초). 0 미만 = 열차가 입장보다 먼저 떠남",
                  xaxis=dict(title="대기시간(초)", range=[-600, 1200]), yaxis_title="승객 비율(30초 구간)", template="plotly_white")
fig.write_html(OUT / "fig1_wait_distribution.html", include_plotlyjs="cdn")

order = ["a_current", "direction_swap", "local_shuffle5", "random_timetable", "station_circular_shift", "shift+60s", "shift-60s"]
lab = {"a_current": "(a) 현재", "direction_swap": "방향 뒤바꿈", "local_shuffle5": "국소 섞기", "random_timetable": "무작위 시간표",
       "station_circular_shift": "역별 원형 이동", "shift+60s": "+60초", "shift-60s": "−60초"}
M = {"a_current": R["metrics_a_all_pax"]["all"], **{k: R["nulls_a"][k]["all"] for k in order[1:]}}
fig2 = make_subplots(rows=1, cols=3, subplot_titles=("음수 대기 비율(낮을수록 좋음)", "창 내 비율 0~600초(높을수록 좋음)", "방향 일치율(높을수록 좋음)"))
for i, key in enumerate(("neg", "window", "dir_match"), 1):
    fig2.add_trace(go.Bar(x=[lab[k] for k in order], y=[M[k][key] for k in order], showlegend=False,
                          marker_color=["#1f77b4"] + ["#aaaaaa"] * 6), row=1, col=i)
ca, cb = R["metrics_a_common_pax"]["all"], R["metrics_b_common_pax"]["all"]
fig2.update_layout(title="기준 시간표 vs 대조 (파란 막대 = 현재). 이동 대조는 참고용(통과 조건 아님)", template="plotly_white", height=420)
fig2.write_html(OUT / "fig2_baseline_vs_controls.html", include_plotlyjs="cdn")
print("ok")
