// Renders the export's figures offline. Radar images are embedded once and resolved here,
// instead of being copied into every figure.
(function () {
  "use strict";
  const radars = JSON.parse(document.getElementById("radars").textContent);
  const colour = getComputedStyle(document.body).color;
  document.querySelectorAll("[data-figure]").forEach((el) => {
    const spec = JSON.parse(document.getElementById(el.dataset.figure).textContent);
    (spec.layout.images || []).forEach((img) => {
      if (img.source && img.source.indexOf("radar://") === 0) {
        img.source = radars[img.source.slice("radar://".length)] || "";
      }
    });
    spec.layout.font = Object.assign({}, spec.layout.font, { color: colour });
    window.Plotly.newPlot(el, spec.data, spec.layout, { displaylogo: false, responsive: true });
  });
})();
