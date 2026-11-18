"""Overlay figure: recorded B<->C trips (2019-01-08) drawn as bands on the line map, colored by (observed - direct-hub-route model) minutes.
Direct hub model = B10-C51 with W fitted (stage 1, branch-aware). Descriptive only; nothing is tuned."""
import sys, json
sys.path.insert(0, "scripts/hangzhou")
import numpy as np, pandas as pd
from lineC_common import *

tr = pd.read_pickle(CACHE / "trips_2019-01-08.pkl")
a = tr[(tr.entry_line == "B") & (tr.exit_line == "C")]; b = tr[(tr.entry_line == "C") & (tr.exit_line == "B")]
bs = np.concatenate([a.entry_st.to_numpy(), b.exit_st.to_numpy()]); cs = np.concatenate([a.exit_st.to_numpy(), b.entry_st.to_numpy()]); m = np.concatenate([a.minutes.to_numpy(), b.minutes.to_numpy()])
dx = b_dist(bs, np.full(len(bs), 10), True); dc = np.abs(np.array([POS["C"][s] for s in cs]) - POS["C"][51])
base = cfun("B", dx) + cfun("C", dc)
W = float(np.median(m - base)); pred = base + W
BG = [("B0–B9", 0, 9), ("B11–B20", 11, 20), ("B21–B27", 21, 27), ("B28–B33 지선", 28, 33)]
CG = [("C34–C45", 34, 45), ("C47–C50", 47, 50), ("C52–C66", 52, 66)]
rows = []
for i, (bn, b0, b1) in enumerate(BG):
    for j, (cn, c0, c1) in enumerate(CG):
        k = (bs >= b0) & (bs <= b1) & (cs >= c0) & (cs <= c1)
        if k.sum() < 200: continue
        r = m[k] - pred[k]
        rows.append(dict(bi=i, cj=j, bn=bn, cn=cn, n=int(k.sum()), obs=float(np.median(m[k])), pred=float(np.median(pred[k])), diff=float(np.median(r)), within5=float((np.abs(r) <= 5).mean())))
df = pd.DataFrame(rows); df["id"] = range(1, len(df) + 1)
df.round(3).to_csv(ROOT / "outputs/hangzhou/lineC/overlay_bundles.csv", index=False); print(W); print(df.round(2).to_string())

# ---- drawing ----
bx = lambda i: 50 + i * 20
by, cy = 120, 420
cx = lambda i: 46 + (i - 34) * 12
Bc = [bx(4.5), bx(15.5), bx(24), 545]; Byy = [by, by, by, 150]
Cc = [(cx(34) + cx(45)) / 2, (cx(47) + cx(50)) / 2, (cx(52) + cx(66)) / 2]
col = lambda d: "#C4452C" if d <= -4 else "#E0892B" if d <= -2 else "#3B8BD4" if d >= 4 else "#9AA59E"
o = []
T = lambda x, y, s, w=400, c="#13201A", sz=12, a="start": o.append(f'<text x="{x}" y="{y}" text-anchor="{a}" dominant-baseline="central" style="font-size:{sz}px;font-weight:{w};fill:{c}">{s}</text>')
bar = lambda d, c, w=7: o.append(f'<path d="{d}" stroke="{c}" stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round" fill="none"/>')
T(40, 24, "B선(1호선 추정)", 500); T(40, cy + 40, "C선(2호선 추정)", 500)
bar(f"M{bx(0)} {by} H{bx(27)}", "#1D9E75"); bar(f"M{bx(20)} {by} L{bx(20)+14} {by+30} H{bx(33-28+23)+60}", "#1D9E75")
bar(f"M{cx(34)} {cy} H{cx(66)}", "#7F77DD"); bar(f"M{cx(46)} {cy} V{cy-70}", "#D85A30")
for i in range(28): o.append(f'<circle cx="{bx(i)}" cy="{by}" r="3" fill="#fff"/>')
for i in range(34, 67): o.append(f'<circle cx="{cx(i)}" cy="{cy}" r="3" fill="#fff"/>')
for i, x in enumerate([bx(5), bx(10), bx(15), bx(16)]): pass
for lab, x, y in [("B10", bx(10), by), ("B15", bx(15), by), ("B16", bx(16), by), ("B5", bx(5), by)]: o.append(f'<circle cx="{x}" cy="{y}" r="7" fill="#fff" stroke="#13201A" stroke-width="2"/>'); T(x, y - 16, lab, 500, a="middle")
for lab, x in [("C51", cx(51)), ("C46", cx(46))]: o.append(f'<circle cx="{x}" cy="{cy}" r="7" fill="#fff" stroke="#13201A" stroke-width="2"/>'); T(x, cy + 18, lab, 500, a="middle")
T(cx(46) - 8, cy - 40, "A77~A80", 400, "#4A5650", 12, "end")
T(bx(20) + 22, by + 46, "B28–B33", 400, "#4A5650", 11)
bands = []
for _, r in df.iterrows():
    x1, y1, x2, y2 = Bc[int(r.bi)], Byy[int(r.bi)] + 8, Cc[int(r.cj)], cy - 8
    w = 3 + 14 * r.n / df.n.max()
    d = f"M{x1:.1f} {y1} C{x1:.1f} {y1+130},{x2:.1f} {y2-130},{x2:.1f} {y2}"
    bands.append(f'<path d="{d}" stroke="{col(r["diff"])}" stroke-width="{w:.1f}" stroke-opacity="0.6" fill="none" stroke-linecap="round"/>')
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    bands.append(f'<circle cx="{mx:.1f}" cy="{my:.1f}" r="9" fill="#fff" stroke="#13201A" stroke-width="1"/><text x="{mx:.1f}" y="{my:.1f}" text-anchor="middle" dominant-baseline="central" style="font-size:11px;font-weight:500;fill:#13201A">{int(r.id)}</text>')
# via-A hypothesis (dashed)
o_via = f'<path d="M{bx(16)} {by+8} L{cx(46)} {cy-70}" stroke="#13201A" stroke-width="2" stroke-dasharray="6 4" fill="none"/>'
body = "\n".join(o[:0]) 
svg = "\n".join(o) + "\n" + "\n".join(bands) + "\n" + o_via
leg = [("#C4452C", "관측이 직접 경로 예상보다 4분 이상 빠름"), ("#E0892B", "2~4분 빠름"), ("#9AA59E", "비슷함(±2분)"), ("#3B8BD4", "4분 이상 느림")]
lx = "".join(f'<rect x="{40}" y="{470+k*20}" width="22" height="8" fill="{c}" fill-opacity="0.8"/><text x="70" y="{474+k*20}" dominant-baseline="central" style="font-size:12px;fill:#13201A">{t}</text>' for k, (c, t) in enumerate(leg))
lx += '<path d="M40 556 H62" stroke="#13201A" stroke-width="2" stroke-dasharray="6 4"/><text x="70" y="556" dominant-baseline="central" style="font-size:12px;fill:#13201A">B16에서 A선을 거쳐 C46으로 가는 길(가설)</text>'
trow = "".join(f'<tr><td>{int(r.id)}</td><td>{r.bn} ↔ {r.cn}</td><td>{int(r.n):,}</td><td>{r.obs:.1f}분</td><td>{r.pred:.1f}분</td><td style="color:{col(r["diff"])};font-weight:500">{r["diff"]:+.1f}분</td></tr>' for _, r in df.iterrows())
html = f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>항저우 B-C 이동 겹쳐 보기</title><style>body{{margin:0;background:#fff;color:#13201A;font-family:'Noto Sans KR',system-ui,sans-serif}}main{{max-width:760px;margin:0 auto;padding:12px}}svg{{display:block;width:100%}}table{{border-collapse:collapse;width:100%;font-size:13px;margin-top:8px}}th,td{{padding:4px 8px;border-bottom:1px solid #D9DFDA;text-align:left}}th{{font-weight:500;color:#4A5650}}td:nth-child(n+3){{text-align:right}}h1{{font-size:16px;font-weight:500}}p{{font-size:13px;color:#4A5650;margin:4px 0}}</style></head><body><main><h1>B선과 C선 사이 이동(2019-01-08)을 노선도 위에 겹쳐 본 것</h1><p>각 띠는 한 구간 묶음의 이동입니다. 두께는 이동 수, 색은 (실제 걸린 시간) − (B10에서 C51로 갈아탄다고 가정한 예상)입니다. 빨강은 직접 경로로는 불가능하게 빠르게 도착한 이동입니다.</p><svg viewBox="0 0 680 590" role="img" aria-label="B선과 C선 사이 이동 띠와 소요시간 차이">{svg}{lx}</svg><table><tr><th>번호</th><th>구간 (B 출발·도착 ↔ C)</th><th>이동 수</th><th>실제 중앙값</th><th>직접 경로 예상</th><th>차이</th></tr>{trow}</table><p>직접 경로 예상 = B10까지 + 환승 대기 {W:.1f}분 + C51부터(같은 노선 이동 시간 모형, 01-08 하루). 양방향(B→C, C→B)을 합쳤습니다. 환승역과 노선 모양은 노선도 정보에서 추정했습니다.</p></main></body></html>'''
open("design/hangzhou_overlay.html", "w", encoding="utf-8").write(html)
