// Sends the per-launch session token with every htmx request (design §8) and renders
// Plotly figures whose specs the server embeds as JSON (ADR-001).
(function () {
  "use strict";
  const token = document.querySelector('meta[name="cs2scout-token"]').content;
  document.addEventListener("htmx:configRequest", (event) => {
    event.detail.headers["X-CS2Scout"] = token;
  });

  function renderCharts(root) {
    root.querySelectorAll("[data-figure]").forEach((el) => {
      if (el.dataset.rendered) return;
      const spec = JSON.parse(document.getElementById(el.dataset.figure).textContent);
      const style = getComputedStyle(document.body);
      spec.layout.font = Object.assign({}, spec.layout.font, { color: style.color });
      window.Plotly.newPlot(el, spec.data, spec.layout, { displaylogo: false, responsive: true });
      el.dataset.rendered = "1";
    });
  }
  document.addEventListener("DOMContentLoaded", () => renderCharts(document));
  document.addEventListener("htmx:afterSettle", (event) => renderCharts(event.detail.elt));

  // Export: optionally carry the filter form's values into the download link.
  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!form.matches("form[data-export]")) return;
    event.preventDefault();
    const params = new URLSearchParams(new FormData(form));
    if (params.has("use_filters")) {
      new FormData(document.getElementById("filters")).forEach((v, k) => params.append(k, v));
    }
    params.delete("use_filters");
    window.location.href = form.action + "?" + params.toString();
  });

  // Close the round drawer with Escape.
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") document.getElementById("drawer").innerHTML = "";
  });
})();
