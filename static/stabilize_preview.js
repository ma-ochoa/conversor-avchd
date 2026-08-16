// Previsualización de estabilización en el navegador: aplica el suavizado y el zoom
// a un vídeo proxy mediante <canvas>, sin necesidad de recodificar nada en el
// servidor. Compartido entre Montaje y Estabilización — cada página crea su propia
// instancia con createStabilizePreview() apuntando a sus propios elementos del DOM.
//
// El zoom que se ve aquí es una aproximación (ver autoZoomPercent), nunca será
// idéntico al cálculo real de vid.stab (que usa un algoritmo de optimización más
// sofisticado) — solo orienta visualmente antes de decidir si merece la pena analizar.

function medianAbs(values) {
  const sorted = values.map(Math.abs).sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function computeCorrections(analysis, smoothingWindow) {
  const n = analysis.path.length;
  // Algún fotograma aislado con poco contraste puede dar un valor de movimiento
  // disparatado; se recorta a 4x la mediana para que no arrastre el resto de la
  // trayectoria acumulada (si no, un solo fotograma malo desplaza todo lo siguiente).
  const dxs = analysis.path.map((f) => f.dx);
  const dys = analysis.path.map((f) => f.dy);
  const limX = Math.max(medianAbs(dxs) * 4, 1);
  const limY = Math.max(medianAbs(dys) * 4, 1);
  const clamp = (v, lim) => Math.max(-lim, Math.min(lim, v));

  const cumX = new Array(n), cumY = new Array(n), cumA = new Array(n);
  let x = 0, y = 0, a = 0;
  for (let i = 0; i < n; i++) {
    x += clamp(analysis.path[i].dx, limX);
    y += clamp(analysis.path[i].dy, limY);
    a += analysis.path[i].angle;
    cumX[i] = x; cumY[i] = y; cumA[i] = a;
  }
  const w = Math.max(smoothingWindow, 0);
  const smoothX = new Array(n), smoothY = new Array(n), smoothA = new Array(n);
  for (let i = 0; i < n; i++) {
    const lo = Math.max(0, i - w), hi = Math.min(n - 1, i + w);
    let sx = 0, sy = 0, sa = 0;
    for (let j = lo; j <= hi; j++) { sx += cumX[j]; sy += cumY[j]; sa += cumA[j]; }
    const count = hi - lo + 1;
    smoothX[i] = sx / count; smoothY[i] = sy / count; smoothA[i] = sa / count;
  }
  const corrections = new Array(n);
  let maxAbs = 0;
  for (let i = 0; i < n; i++) {
    const ox = smoothX[i] - cumX[i], oy = smoothY[i] - cumY[i], oa = smoothA[i] - cumA[i];
    corrections[i] = { ox, oy, oa };
    maxAbs = Math.max(maxAbs, Math.abs(ox), Math.abs(oy));
  }
  return { corrections, maxAbs };
}

function autoZoomPercent(analysis, maxAbs) {
  const dim = Math.min(analysis.width, analysis.height);
  if (!dim) return 5;
  return Math.min(40, Math.max(1, (2 * maxAbs / dim) * 100));
}

// elements: { video, canvas, seek, playBtn, toggle } — playBtn es opcional (la
// reproducción con requestAnimationFrame también puede pilotarse a mano).
function createStabilizePreview({ video, canvas, seek, playBtn, toggle }) {
  const ctx = canvas.getContext("2d");
  let analysis = null;
  let corrections = null;
  let rafId = null;

  function setupPreview(newAnalysis) {
    analysis = newAnalysis;
    corrections = null;
    video.src = `/media?path=${encodeURIComponent(analysis.proxy_path)}`;
    video.load();
    return new Promise((resolve) => {
      video.addEventListener("loadedmetadata", () => {
        seek.max = video.duration || analysis.duration;
        resolve();
      }, { once: true });
    });
  }

  function recomputeAndRender(params) {
    if (!analysis) return;
    const result = computeCorrections(analysis, params.smoothing);
    const zoomPercent = params.zoom_mode === "manual"
      ? params.zoom_percent
      : autoZoomPercent(analysis, result.maxAbs);
    corrections = { ...result, zoomPercent };
    renderFrame();
  }

  function renderFrame() {
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    if (video.readyState < 2) return;

    const useCorrection = toggle.checked && corrections;
    if (!useCorrection) {
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      return;
    }

    const fps = analysis.fps || 25;
    const idx = Math.min(
      corrections.corrections.length - 1,
      Math.max(0, Math.round(video.currentTime * fps)),
    );
    const c = corrections.corrections[idx];
    const scaleX = canvas.width / analysis.width;
    const scaleY = canvas.height / analysis.height;
    const zoom = 1 + (corrections.zoomPercent || 0) / 100;

    ctx.save();
    ctx.translate(canvas.width / 2, canvas.height / 2);
    ctx.rotate(c.oa);
    ctx.scale(zoom, zoom);
    ctx.translate(-canvas.width / 2 + c.ox * scaleX, -canvas.height / 2 + c.oy * scaleY);
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    ctx.restore();
  }

  function renderLoop() {
    renderFrame();
    seek.value = video.currentTime;
    if (!video.paused && !video.ended) {
      rafId = requestAnimationFrame(renderLoop);
    }
  }

  function stop() {
    if (rafId) cancelAnimationFrame(rafId);
    rafId = null;
    video.pause();
    if (playBtn) playBtn.textContent = "▶️";
  }

  function play() {
    video.play();
    if (playBtn) playBtn.textContent = "⏸️";
    rafId = requestAnimationFrame(renderLoop);
  }

  if (playBtn) {
    playBtn.addEventListener("click", () => {
      if (video.paused) play(); else stop();
    });
  }
  seek.addEventListener("input", () => {
    stop();
    video.currentTime = parseFloat(seek.value);
  });
  video.addEventListener("seeked", renderFrame);
  toggle.addEventListener("change", renderFrame);

  return {
    setupPreview,
    recomputeAndRender,
    renderFrame,
    stop,
    play,
    getAnalysis: () => analysis,
    getCorrections: () => corrections,
  };
}
