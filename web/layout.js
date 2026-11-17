/* 사용자가 조절하는 레이아웃: 왼쪽 패널 너비, 추천 결과 높이, 각 패널 접기/펴기.
   크기는 localStorage 에 저장한다(없어도 동작). 좁은 화면(<=860px)에서는 사용하지 않는다. */
(function () {
  const KEY = 'layout.v1';
  const $ = id => document.getElementById(id);
  const layout = document.querySelector('.main-layout');
  const panel = $('controlPanel');
  const right = document.querySelector('.right-col');
  const sec = $('resultsSection');
  const splitV = $('splitV');
  const splitH = $('splitH');
  if (!layout || !panel || !right || !sec || !splitV || !splitH) return;

  const narrow = window.matchMedia('(max-width: 860px)');
  const saved = { panelW: null, resultsH: null, panelCollapsed: false, resultsCollapsed: false };
  try { Object.assign(saved, JSON.parse(localStorage.getItem(KEY) || '{}')); } catch (_) { /* 저장소 없음 */ }
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(saved)); } catch (_) { /* 무시 */ } };
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  let raf = 0;
  const relayout = () => {
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(() => { try { state.map?.relayout(); } catch (_) { /* 지도 없음 */ } });
  };

  const panelLimits = () => ({ min: 240, max: Math.max(260, Math.min(560, Math.floor(layout.clientWidth * 0.6))) });
  const resultsLimits = () => ({ min: 96, max: Math.max(120, right.clientHeight - splitH.offsetHeight - 200) });

  function setPanelW(px, persist) {
    const { min, max } = panelLimits();
    const v = Math.round(clamp(px, min, max));
    document.documentElement.style.setProperty('--panel-w', v + 'px');
    splitV.setAttribute('aria-valuemin', String(min));
    splitV.setAttribute('aria-valuemax', String(max));
    splitV.setAttribute('aria-valuenow', String(v));
    if (persist) { saved.panelW = v; save(); }
    relayout();
    return v;
  }

  function setResultsH(px, persist) {
    const { min, max } = resultsLimits();
    const v = Math.round(clamp(px, min, max));
    sec.style.height = v + 'px';
    sec.classList.add('is-sized');
    splitH.setAttribute('aria-valuemin', String(min));
    splitH.setAttribute('aria-valuemax', String(max));
    splitH.setAttribute('aria-valuenow', String(v));
    if (persist) { saved.resultsH = v; save(); }
    relayout();
    return v;
  }

  function applyCollapse() {
    layout.classList.toggle('panel-collapsed', !!saved.panelCollapsed);
    sec.classList.toggle('collapsed', !!saved.resultsCollapsed);
    right.classList.toggle('results-collapsed', !!saved.resultsCollapsed);
    const pt = $('panelToggle'), rt = $('resultsToggle');
    if (pt) { pt.textContent = saved.panelCollapsed ? '패널 펴기' : '패널 접기'; pt.setAttribute('aria-expanded', String(!saved.panelCollapsed)); }
    if (rt) { rt.textContent = saved.resultsCollapsed ? '결과 펴기' : '결과 접기'; rt.setAttribute('aria-expanded', String(!saved.resultsCollapsed)); }
  }

  function applyAll() {
    if (narrow.matches) {
      document.documentElement.style.removeProperty('--panel-w');
      sec.style.height = '';
      sec.classList.remove('is-sized');
      relayout();
      return;
    }
    if (saved.panelW) setPanelW(saved.panelW, false); else setPanelW(panel.getBoundingClientRect().width || 318, false);
    if (saved.resultsH) setResultsH(saved.resultsH, false);
    else { const h = sec.getBoundingClientRect().height; splitH.setAttribute('aria-valuenow', String(Math.round(h))); const l = resultsLimits(); splitH.setAttribute('aria-valuemin', String(l.min)); splitH.setAttribute('aria-valuemax', String(l.max)); }
    applyCollapse();
    relayout();
  }

  function drag(el, onMove, onEnd) {
    el.addEventListener('pointerdown', ev => {
      if (narrow.matches || ev.button > 0) return;
      ev.preventDefault();
      el.setPointerCapture(ev.pointerId);
      el.classList.add('dragging');
      document.body.classList.add('is-resizing');
      const move = e => onMove(e);
      const up = e => {
        el.releasePointerCapture?.(e.pointerId);
        el.removeEventListener('pointermove', move);
        el.removeEventListener('pointerup', up);
        el.removeEventListener('pointercancel', up);
        el.classList.remove('dragging');
        document.body.classList.remove('is-resizing');
        onEnd();
      };
      el.addEventListener('pointermove', move);
      el.addEventListener('pointerup', up);
      el.addEventListener('pointercancel', up);
      el._start = { x: ev.clientX, y: ev.clientY, w: panel.getBoundingClientRect().width, h: sec.getBoundingClientRect().height };
    });
  }

  drag(splitV, e => setPanelW(splitV._start.w + (e.clientX - splitV._start.x), false), () => setPanelW(Number(splitV.getAttribute('aria-valuenow')), true));
  drag(splitH, e => setResultsH(splitH._start.h - (e.clientY - splitH._start.y), false), () => setResultsH(Number(splitH.getAttribute('aria-valuenow')), true));

  splitV.addEventListener('keydown', e => {
    const step = e.shiftKey ? 64 : 16, now = Number(splitV.getAttribute('aria-valuenow')) || panel.offsetWidth;
    const { min, max } = panelLimits();
    const map = { ArrowRight: now + step, ArrowLeft: now - step, Home: min, End: max };
    if (!(e.key in map)) return;
    e.preventDefault();
    setPanelW(map[e.key], true);
  });
  splitH.addEventListener('keydown', e => {
    const step = e.shiftKey ? 64 : 16, now = Number(splitH.getAttribute('aria-valuenow')) || sec.offsetHeight;
    const { min, max } = resultsLimits();
    const map = { ArrowUp: now + step, ArrowDown: now - step, Home: min, End: max };
    if (!(e.key in map)) return;
    e.preventDefault();
    setResultsH(map[e.key], true);
  });

  $('panelToggle')?.addEventListener('click', () => { saved.panelCollapsed = !saved.panelCollapsed; save(); applyCollapse(); relayout(); });
  $('resultsToggle')?.addEventListener('click', () => { saved.resultsCollapsed = !saved.resultsCollapsed; save(); applyCollapse(); relayout(); });

  let resizeTimer = 0;
  window.addEventListener('resize', () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(applyAll, 120); });
  narrow.addEventListener?.('change', applyAll);
  applyAll();
})();
