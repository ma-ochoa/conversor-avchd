// Panel de parámetros de estabilización compartido (templates/_stab_params_panel.html)
// — usado en el panel masivo de Estabilización, el modal por clip de Estabilización, y
// el modal de Montaje, cada uno con su propio prefijo de ids. En modo "Automático" los
// controles están siempre visibles pero bloqueados (disabled), mostrando los valores de
// fábrica; en "Personalizado" se desbloquean.

const STAB_DEFAULT_PARAMS = {
  shakiness: 5, accuracy: 15, smoothing: 10,
  zoom_mode: "auto_static", zoom_percent: 0,
  stepsize: 6, mincontrast: 0.25,
  interpol: "bilinear", optalgo: "gauss",
  maxshift: -1, maxangle: -1,
};

function stabIsCustom(params) {
  return Object.keys(STAB_DEFAULT_PARAMS).some((key) => {
    const value = params[key] === undefined ? STAB_DEFAULT_PARAMS[key] : params[key];
    return String(value) !== String(STAB_DEFAULT_PARAMS[key]);
  });
}

function createStabParamsPanel(prefix, { onChange } = {}) {
  const byId = (suffix) => document.getElementById(`${prefix}-${suffix}`);

  const el = {
    modeAuto: byId("mode-auto"),
    modeCustom: byId("mode-custom"),
    shakiness: byId("shakiness"),
    shakinessValue: byId("shakiness-value"),
    smoothing: byId("smoothing"),
    smoothingValue: byId("smoothing-value"),
    zoomMode: byId("zoom-mode"),
    zoomPercent: byId("zoom-percent"),
    zoomPercentValue: byId("zoom-percent-value"),
    zoomPercentRow: byId("zoom-percent-row"),
    accuracy: byId("accuracy"),
    accuracyValue: byId("accuracy-value"),
    stepsize: byId("stepsize"),
    stepsizeValue: byId("stepsize-value"),
    mincontrast: byId("mincontrast"),
    mincontrastValue: byId("mincontrast-value"),
    interpol: byId("interpol"),
    optalgo: byId("optalgo"),
    maxshift: byId("maxshift"),
    maxshiftValue: byId("maxshift-value"),
    maxangle: byId("maxangle"),
    maxangleValue: byId("maxangle-value"),
  };

  const lockableInputs = [
    el.shakiness, el.smoothing, el.zoomMode, el.zoomPercent,
    el.accuracy, el.stepsize, el.mincontrast, el.interpol, el.optalgo, el.maxshift, el.maxangle,
  ];

  function formatShift(value) {
    return Number(value) < 0 ? "sin límite" : `${value}px`;
  }
  function formatAngle(value) {
    return Number(value) < 0 ? "sin límite" : `${value}°`;
  }

  function refreshLabels() {
    el.shakinessValue.textContent = el.shakiness.value;
    el.smoothingValue.textContent = el.smoothing.value;
    el.zoomPercentValue.textContent = el.zoomPercent.value;
    el.zoomPercentRow.classList.toggle("hidden", el.zoomMode.value !== "manual");
    el.accuracyValue.textContent = el.accuracy.value;
    el.stepsizeValue.textContent = el.stepsize.value;
    el.mincontrastValue.textContent = el.mincontrast.value;
    el.maxshiftValue.textContent = formatShift(el.maxshift.value);
    el.maxangleValue.textContent = formatAngle(el.maxangle.value);
  }

  function setLocked(locked) {
    lockableInputs.forEach((input) => (input.disabled = locked));
  }

  function notify() {
    refreshLabels();
    if (onChange) onChange(getParams());
  }

  lockableInputs.forEach((input) => {
    input.addEventListener("input", notify);
    input.addEventListener("change", notify);
  });
  document.querySelectorAll(`input[name="${prefix}-mode"]`).forEach((radio) => {
    radio.addEventListener("change", () => {
      setLocked(el.modeAuto.checked);
      notify();
    });
  });

  function getParams() {
    return {
      shakiness: parseInt(el.shakiness.value, 10),
      accuracy: parseInt(el.accuracy.value, 10),
      smoothing: parseInt(el.smoothing.value, 10),
      zoom_mode: el.zoomMode.value,
      zoom_percent: parseFloat(el.zoomPercent.value),
      stepsize: parseInt(el.stepsize.value, 10),
      mincontrast: parseFloat(el.mincontrast.value),
      interpol: el.interpol.value,
      optalgo: el.optalgo.value,
      maxshift: parseInt(el.maxshift.value, 10),
      maxangle: parseFloat(el.maxangle.value),
    };
  }

  // params=null o {} restablece a los valores de fábrica en modo automático.
  function setParams(params) {
    const p = { ...STAB_DEFAULT_PARAMS, ...(params || {}) };
    el.shakiness.value = p.shakiness;
    el.accuracy.value = p.accuracy;
    el.smoothing.value = p.smoothing;
    el.zoomMode.value = p.zoom_mode;
    el.zoomPercent.value = p.zoom_percent;
    el.stepsize.value = p.stepsize;
    el.mincontrast.value = p.mincontrast;
    el.interpol.value = p.interpol;
    el.optalgo.value = p.optalgo;
    el.maxshift.value = p.maxshift;
    el.maxangle.value = p.maxangle;

    const custom = params ? stabIsCustom(params) : false;
    el.modeAuto.checked = !custom;
    el.modeCustom.checked = custom;
    setLocked(!custom);
    refreshLabels();
  }

  setParams(null);
  return { getParams, setParams, element: el };
}
