/* 사용자가 조절하는 레이아웃(D-017, 디자인 v2에서 오른쪽 결과 패널 기준으로 변경):
   지도와 결과 패널 사이 분할선으로 패널 너비를 조절하고, 버튼으로 패널을 접고 편다.
   크기는 localStorage 에 저장한다(없어도 동작). 좁은 화면(<=860px)에서는 쓰지 않는다. */
(function () {
  const KEY = 'layout.v2';
  const $ = id => document.getElementById(id);
  const layout = document.querySelector('.main-layout');
  const panel = $('resultsSection');
  const splitV = $('splitV');
  const toggle = $('panelToggle');
  if (!layout || !panel || !splitV) return;

  const narrow = window.matchMedia('(max-width: 860px)');
  const saved = { panelW: null, collapsed: false };
  try { Object.assign(saved, JSON.parse(localStorage.getItem(KEY) || '{}')); } catch (_) { /* 저장소 없음 */ }
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(saved)); } catch (_) { /* 무시 */ } };
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  let raf = 0;
  const relayout = () => {
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(() => { try { state.map?.relayout(); } catch (_) { /* 지도 없음 */ } });
  };
  const limits = () => ({ min: 300, max: Math.max(320, Math.min(640, Math.floor(layout.clientWidth * 0.6))) });

  function setPanelW(px, persist) {
    const { min, max } = limits();
    const v = Math.round(clamp(px, min, max));
    document.documentElement.style.setProperty('--results-w', v + 'px');
    splitV.setAttribute('aria-valuemin', String(min));
    splitV.setAttribute('aria-valuemax', String(max));
    splitV.setAttribute('aria-valuenow', String(v));
    if (persist) { saved.panelW = v; save(); }
    relayout();
    return v;
  }

  function applyCollapse() {
    layout.classList.toggle('results-collapsed', !!saved.collapsed);
    if (toggle) {
      toggle.textContent = saved.collapsed ? '결과 펴기' : '결과 접기';
      toggle.setAttribute('aria-expanded', String(!saved.collapsed));
    }
  }

  function applyAll() {
    if (narrow.matches) {
      document.documentElement.style.removeProperty('--results-w');
      relayout();
      return;
    }
    setPanelW(saved.panelW || panel.getBoundingClientRect().width || 360, false);
    applyCollapse();
    relayout();
  }

  splitV.addEventListener('pointerdown', ev => {
    if (narrow.matches || ev.button > 0) return;
    ev.preventDefault();
    splitV.setPointerCapture(ev.pointerId);
    splitV.classList.add('dragging');
    document.body.classList.add('is-resizing');
    const startX = ev.clientX, startW = panel.getBoundingClientRect().width;
    const move = e => setPanelW(startW - (e.clientX - startX), false); // 패널이 오른쪽에 있어 왼쪽으로 끌면 넓어진다
    const up = e => {
      splitV.releasePointerCapture?.(e.pointerId);
      splitV.removeEventListener('pointermove', move);
      splitV.removeEventListener('pointerup', up);
      splitV.removeEventListener('pointercancel', up);
      splitV.classList.remove('dragging');
      document.body.classList.remove('is-resizing');
      setPanelW(Number(splitV.getAttribute('aria-valuenow')), true);
    };
    splitV.addEventListener('pointermove', move);
    splitV.addEventListener('pointerup', up);
    splitV.addEventListener('pointercancel', up);
  });

  splitV.addEventListener('keydown', e => {
    const step = e.shiftKey ? 64 : 16, now = Number(splitV.getAttribute('aria-valuenow')) || panel.offsetWidth;
    const { min, max } = limits();
    const map = { ArrowLeft: now + step, ArrowRight: now - step, Home: min, End: max };
    if (!(e.key in map)) return;
    e.preventDefault();
    setPanelW(map[e.key], true);
  });

  toggle?.addEventListener('click', () => { saved.collapsed = !saved.collapsed; save(); applyCollapse(); relayout(); });

  let resizeTimer = 0;
  window.addEventListener('resize', () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(applyAll, 120); });
  narrow.addEventListener?.('change', applyAll);
  applyAll();
})();
