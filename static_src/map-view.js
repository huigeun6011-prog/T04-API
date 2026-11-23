/* Interactive presentation of Kakao REST static-map images.
 * No Kakao SDK, app key, authorization header, or upstream URL reaches this file.
 * Projection is supplied by the verified, local MapViewProjection module.
 */
(function () {
  'use strict';
  const svgNS = 'http://www.w3.org/2000/svg';
  const clamp = (n, lo, hi) => Math.min(hi, Math.max(lo, n));
  class LatLng {
    constructor(lat, lng) { this.lat = Number(lat); this.lng = Number(lng); }
    getLat() { return this.lat; }
    getLng() { return this.lng; }
  }
  function projection() {
    const p = window.MapViewProjection;
    if (!p || typeof p.forward !== 'function' || typeof p.inverse !== 'function') throw new Error('Map projection unavailable');
    return p;
  }
  class MapView {
    constructor(element, options = {}) {
      this.element = element;
      this.center = options.center || new LatLng(36.3515, 127.3867);
      this.level = clamp(options.level || 6, 1, 15);
      this.listeners = new globalThis.Map();
      this.overlays = new Set();
      this.lines = new Set();
      this.requestId = 0;
      this.imageCenter = null;
      this.imageLevel = null;
      this.imageUrl = null;
      this.controller = null;
      element.classList.add('rest-map');
      element.tabIndex = 0;
      element.setAttribute('aria-keyshortcuts', 'ArrowUp ArrowDown ArrowLeft ArrowRight + -');
      this.image = document.createElement('img');
      this.image.className = 'rest-map-image';
      this.image.alt = '';
      this.image.draggable = false;
      this.svg = document.createElementNS(svgNS, 'svg');
      this.svg.classList.add('rest-map-vectors');
      this.svg.setAttribute('aria-hidden', 'true');
      this.layer = document.createElement('div');
      this.layer.className = 'rest-map-overlays';
      this.controls = document.createElement('div');
      this.controls.className = 'rest-map-controls';
      this.controls.setAttribute('role', 'group');
      this.controls.setAttribute('aria-label', '지도 확대와 축소');
      this.zoomIn = this.button('+', '지도 확대', () => this.setLevel(this.level - 1));
      this.zoomOut = this.button('−', '지도 축소', () => this.setLevel(this.level + 1));
      this.controls.append(this.zoomIn, this.zoomOut);
      this.status = document.createElement('div');
      this.status.className = 'rest-map-status';
      this.status.setAttribute('role', 'status');
      this.status.textContent = '지도를 불러오는 중입니다.';
      this.error = document.createElement('div');
      this.error.className = 'rest-map-error';
      this.error.hidden = true;
      const card = document.createElement('div');
      card.className = 'rest-map-error-card';
      const title = document.createElement('strong');
      title.textContent = '지도를 불러오지 못했어요';
      const message = document.createElement('div');
      message.textContent = '다시 시도하거나 출발지 선택에서 역을 골라 추천을 이용해 주세요.';
      card.append(title, message, this.button('다시 불러오기', '지도 다시 불러오기', () => this.requestImage()));
      this.error.append(card);
      const hint = document.createElement('div');
      hint.className = 'rest-map-hint';
      hint.textContent = '드래그로 이동 · + / − 확대와 축소';
      element.replaceChildren(this.image, this.svg, this.layer, hint, this.controls, this.status, this.error);
      this.bindInteractions();
      if (typeof ResizeObserver === 'function') {
        this.observer = new ResizeObserver(() => this.relayout());
        this.observer.observe(element);
      }
      this.relayout();
    }
    button(text, label, action) {
      const button = document.createElement('button');
      button.type = 'button'; button.textContent = text; button.setAttribute('aria-label', label);
      button.addEventListener('click', e => { e.stopPropagation(); action(); });
      return button;
    }
    emit(type, data) { (this.listeners.get(type) || []).forEach(callback => callback(data)); }
    getCenter() { return this.center; }
    getLevel() { return this.level; }
    metersPerPixel() { return 2 ** (this.level - 3); }
    point(coords) {
      const p = projection().forward(coords.getLat(), coords.getLng());
      const c = projection().forward(this.center.getLat(), this.center.getLng());
      const scale = this.metersPerPixel();
      return { x: this.width / 2 + (p.x - c.x) / scale, y: this.height / 2 - (p.y - c.y) / scale };
    }
    coordsAt(x, y) {
      const c = projection().forward(this.center.getLat(), this.center.getLng());
      const scale = this.metersPerPixel();
      const coords = projection().inverse(c.x + (x - this.width / 2) * scale, c.y - (y - this.height / 2) * scale);
      return new LatLng(coords.lat, coords.lng);
    }
    getProjection() { return { containerPointFromCoords: coords => this.point(coords) }; }
    setCenter(coords) {
      if (!Number.isFinite(coords.getLat()) || !Number.isFinite(coords.getLng())) return;
      this.center = coords;
      this.render(); this.scheduleImage();
    }
    setLevel(level) {
      const next = clamp(Math.round(level), 1, 15);
      if (next === this.level) return;
      this.level = next;
      this.render(); this.scheduleImage();
    }
    panBy(x, y) { this.setCenter(this.coordsAt(this.width / 2 + x, this.height / 2 + y)); }
    relayout() {
      const width = this.element.clientWidth, height = this.element.clientHeight;
      if (!width || !height) return;
      const changed = width !== this.width || height !== this.height;
      this.width = width; this.height = height;
      this.svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
      this.render();
      if (changed) this.scheduleImage();
    }
    render() {
      this.zoomIn.disabled = this.level <= 1;
      this.zoomOut.disabled = this.level >= 15;
      if (this.imageCenter) {
        const p = this.point(this.imageCenter);
        const ratio = 2 ** (this.imageLevel - this.level);
        const width = this.imageWidth * ratio, height = this.imageHeight * ratio;
        Object.assign(this.image.style, { left: `${p.x - width / 2}px`, top: `${p.y - height / 2}px`, width: `${width}px`, height: `${height}px` });
      }
      this.overlays.forEach(overlay => overlay.render());
      this.lines.forEach(line => line.render());
    }
    scheduleImage() {
      // Cancel immediately, including during drag/zoom debounce, so old images cannot win a race.
      this.controller?.abort();
      this.requestId++;
      clearTimeout(this.timer);
      this.timer = setTimeout(() => this.requestImage(), 160);
    }
    async requestImage() {
      clearTimeout(this.timer);
      if (!this.width || !this.height) return;
      this.controller?.abort();
      const id = ++this.requestId;
      const controller = new AbortController();
      this.controller = controller;
      const center = this.center, level = this.level;
      const width = Math.min(2048, Math.round(this.width)), height = Math.min(1024, Math.round(this.height));
      this.error.hidden = true;
      this.status.hidden = false;
      this.element.setAttribute('aria-busy', 'true');
      let objectUrl = null;
      try {
        const endpoint = window.MAP_CONFIG?.imageEndpoint;
        if (!endpoint) throw new Error('Map endpoint unavailable');
        const url = new URL(endpoint, document.baseURI);
        url.search = new URLSearchParams({ center: `${center.getLng().toFixed(7)},${center.getLat().toFixed(7)}`, lv: String(level), width: String(width), height: String(height), scale: '1' });
        const response = await fetch(url, { signal: controller.signal, credentials: 'omit', redirect: 'error' });
        if (!response.ok || !/^image\/(png|jpeg)\b/i.test(response.headers.get('content-type') || '')) throw new Error('Map image unavailable');
        objectUrl = URL.createObjectURL(await response.blob());
        const probe = new Image(); probe.src = objectUrl;
        await probe.decode();
        if (id !== this.requestId || controller.signal.aborted) { URL.revokeObjectURL(objectUrl); return; }
        if (probe.naturalWidth !== width || probe.naturalHeight !== height) throw new Error('Map image size mismatch');
        const previous = this.imageUrl;
        this.image.src = objectUrl;
        this.imageUrl = objectUrl;
        objectUrl = null;
        this.imageCenter = center; this.imageLevel = level; this.imageWidth = width; this.imageHeight = height;
        this.render();
        if (previous) URL.revokeObjectURL(previous);
        this.status.hidden = true;
        this.emit('load');
      } catch (error) {
        if (objectUrl) URL.revokeObjectURL(objectUrl);
        if (id !== this.requestId || controller.signal.aborted) return;
        this.status.hidden = true;
        this.error.hidden = false;
        this.emit('error');
      } finally {
        if (id === this.requestId) this.element.removeAttribute('aria-busy');
      }
    }
    zoomAt(level, x, y) {
      const before = this.coordsAt(x, y);
      this.setLevel(level);
      const after = this.point(before);
      this.panBy(after.x - x, after.y - y);
    }
    bindInteractions() {
      const interactive = target => target.closest('button,a,input,select,.rest-map-overlay,.rest-map-error');
      this.element.addEventListener('pointerdown', e => {
        if (!e.isPrimary || e.button !== 0 || this.activePointer != null || interactive(e.target)) return;
        this.activePointer = e.pointerId;
        this.element.focus({ preventScroll: true });
        e.preventDefault();
        this.element.setPointerCapture(e.pointerId);
        const start = { x: e.clientX, y: e.clientY, center: this.center };
        let moved = false;
        const move = event => {
          if (event.pointerId !== this.activePointer) return;
          if (Math.hypot(event.clientX - start.x, event.clientY - start.y) > 4) moved = true;
          if (!moved) return;
          this.center = start.center;
          this.panBy(start.x - event.clientX, start.y - event.clientY);
        };
        const up = event => {
          if (event.pointerId !== this.activePointer) return;
          this.activePointer = null;
          this.element.removeEventListener('pointermove', move);
          this.element.removeEventListener('pointerup', up);
          this.element.removeEventListener('pointercancel', cancel);
          if (this.element.hasPointerCapture(event.pointerId)) this.element.releasePointerCapture(event.pointerId);
          if (!moved) {
            const rect = this.element.getBoundingClientRect();
            this.emit('click', { latLng: this.coordsAt(event.clientX - rect.left, event.clientY - rect.top) });
          }
        };
        const cancel = event => { moved = true; up(event); };
        this.element.addEventListener('pointermove', move);
        this.element.addEventListener('pointerup', up);
        this.element.addEventListener('pointercancel', cancel);
      });
      this.element.addEventListener('wheel', e => {
        if (interactive(e.target)) return;
        e.preventDefault();
        const now = performance.now();
        if (now - (this.lastWheel || 0) < 180) return;
        this.lastWheel = now;
        const rect = this.element.getBoundingClientRect();
        this.zoomAt(this.level + (e.deltaY > 0 ? 1 : -1), e.clientX - rect.left, e.clientY - rect.top);
      }, { passive: false });
      this.element.addEventListener('dblclick', e => {
        if (interactive(e.target)) return;
        e.preventDefault();
        const rect = this.element.getBoundingClientRect();
        this.zoomAt(this.level - 1, e.clientX - rect.left, e.clientY - rect.top);
      });
      this.element.addEventListener('keydown', e => {
        if (e.target !== this.element) return;
        const shifts = { ArrowLeft: [-100, 0], ArrowRight: [100, 0], ArrowUp: [0, -100], ArrowDown: [0, 100] };
        if (shifts[e.key]) { e.preventDefault(); this.panBy(...shifts[e.key]); }
        if (e.key === '+' || e.key === '=') { e.preventDefault(); this.setLevel(this.level - 1); }
        if (e.key === '-' || e.key === '−') { e.preventDefault(); this.setLevel(this.level + 1); }
      });
    }
  }
  class CustomOverlay {
    constructor(options) {
      this.options = options;
      this.element = document.createElement('div');
      this.element.className = 'rest-map-overlay';
      this.element.style.zIndex = String(options.zIndex || 0);
      if (typeof options.content === 'string') this.element.innerHTML = options.content;
      else this.element.append(options.content);
      if (options.map) this.setMap(options.map);
    }
    setMap(map) {
      this.map?.overlays.delete(this);
      this.element.remove();
      this.map = map;
      if (map) { map.overlays.add(this); map.layer.append(this.element); this.render(); }
    }
    render() {
      if (!this.map) return;
      const point = this.map.point(this.options.position);
      const x = this.options.xAnchor ?? 0.5, y = this.options.yAnchor ?? 0.5;
      this.element.style.transform = `translate(${point.x}px,${point.y}px) translate(${-100 * x}%,${-100 * y}%)`;
    }
  }
  class Polyline {
    constructor(options) {
      this.options = { ...options };
      this.element = document.createElementNS(svgNS, 'polyline');
      this.element.setAttribute('fill', 'none');
      this.element.setAttribute('stroke-linecap', 'round');
      this.element.setAttribute('stroke-linejoin', 'round');
      if (options.map) this.setMap(options.map);
    }
    setMap(map) {
      this.map?.lines.delete(this);
      this.element.remove();
      this.map = map;
      if (map) {
        map.lines.add(this);
        [...map.lines].sort((a, b) => (a.options.zIndex || 0) - (b.options.zIndex || 0)).forEach(line => map.svg.append(line.element));
        this.render();
      }
    }
    setOptions(options) { Object.assign(this.options, options); this.render(); }
    render() {
      if (!this.map) return;
      const options = this.options;
      this.element.setAttribute('points', options.path.map(coords => { const p = this.map.point(coords); return `${p.x},${p.y}`; }).join(' '));
      this.element.setAttribute('stroke', options.strokeColor || '#13201a');
      this.element.setAttribute('stroke-width', String(options.strokeWeight || 3));
      this.element.setAttribute('stroke-opacity', String(options.strokeOpacity ?? 1));
      if (options.strokeStyle === 'shortdash') this.element.setAttribute('stroke-dasharray', '5 7');
      else this.element.removeAttribute('stroke-dasharray');
    }
  }
  window.MapView = Object.freeze({
    Map: MapView, LatLng, CustomOverlay, Polyline,
    load: callback => callback(),
    event: { addListener(map, type, callback) { const list = map.listeners.get(type) || []; list.push(callback); map.listeners.set(type, list); } },
  });
})();
