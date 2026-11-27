// Curves of a station's system figures (uPlot), from /api/stations/{id}/metrics,
// refreshed every 10 s when the period runs up to now.
(function () {
  "use strict";
  const root = document.getElementById("charts");
  if (!root || typeof uPlot === "undefined") return;
  const css = getComputedStyle(document.documentElement);
  const v = (name) => css.getPropertyValue(name).trim();
  const palette = [v("--accent"), "#2fbf71", "#e0a020", "#b072ff", "#ff6b6b", "#29b6c6", "#9aa1aa"];
  const C = { text: v("--muted"), grid: v("--line") };
  // side 3 = left, 1 = right (an undefined side draws a horizontal axis).
  const axis = (label, scale = "y", side = 3) => ({
    label, scale, side, stroke: C.text, ticks: { stroke: C.grid },
    grid: { stroke: C.grid, width: 1, show: side === 3 },
  });
  const line = (label, i, scale = "y", extra = {}) =>
    ({ label, stroke: palette[i % palette.length], width: 1.5, scale, spanGaps: false, ...extra });
  const step = { paths: uPlot.paths && uPlot.paths.stepped ? uPlot.paths.stepped({ align: 1 }) : undefined };

  const charts = {
    cpu: (d) => ({
      series: [line("CPU %", 0), line("ptzview %", 1), line("load", 2, "l")],
      axes: [axis("%"), axis("load", "l", 1)],
      data: [d.series.cpu_pct, d.series.ptzview_cpu_pct, d.series.load1],
    }),
    temp: (d) => ({
      series: [line("°C", 4), line("MHz", 0, "f")],
      axes: [axis("°C"), axis("MHz", "f", 1)],
      data: [d.series.temp_c, d.series.cpu_mhz],
    }),
    memory: (d) => ({
      series: [line("RAM available MB", 0), line("CMA free MB", 2)],
      axes: [axis("MB")],
      data: [d.series.mem_available_mb, d.series.cma_free_mb],
    }),
    power: (d) => ({
      series: [line("under-voltage", 4, "y", step), line("throttled", 2, "y", step)],
      axes: [axis("on")],
      scales: { y: { range: [0, 1.1] } },
      data: [d.series.under_voltage, d.series.throttled],
    }),
    net: (d) => {
      const names = Object.keys(d.net);
      return {
        series: names.flatMap((n, i) => [line(`${n} rx`, i), line(`${n} tx`, i, "y", { dash: [4, 4] })]),
        axes: [axis("Mb/s")],
        data: names.flatMap((n) => [d.net[n].rx_mbps, d.net[n].tx_mbps]),
      };
    },
    fps: (d) => {
      const names = Object.keys(d.cameras);
      const errors = d.t.map((_, i) => {
        let sum = null;
        for (const n of names) {
          const e = d.cameras[n].decode_errors[i];
          if (e !== null) sum = (sum || 0) + e;
        }
        return sum;
      });
      return {
        series: [...names.map((n, i) => line(`${n} fps`, i)), line("decode errors", 4, "e")],
        axes: [axis("fps"), axis("errors", "e", 1)],
        data: [...names.map((n) => d.cameras[n].fps), errors],
      };
    },
  };

  const plots = {};
  const shapes = {};
  const width = (el) => Math.max(300, el.clientWidth);

  function draw(d) {
    for (const el of root.querySelectorAll("[data-chart]")) {
      const key = el.dataset.chart;
      const def = charts[key](d);
      const data = [d.t, ...def.data];
      const shape = def.series.map((s) => s.label).join("|");
      if (plots[key] && shapes[key] === shape) { plots[key].setData(data); continue; }
      if (plots[key]) { plots[key].destroy(); el.innerHTML = ""; }
      shapes[key] = shape;
      plots[key] = new uPlot({
        width: width(el), height: 180,
        scales: { x: { time: true }, ...(def.scales || {}) },
        series: [{}, ...def.series],
        axes: [{ stroke: C.text, grid: { stroke: C.grid, width: 1 }, ticks: { stroke: C.grid } }, ...def.axes],
      }, data, el);
    }
    document.getElementById("charts-note").textContent =
      `${d.t.length} points of ${d.bucket_s} s` + (root.dataset.live === "true" ? " · refreshed every 10 s." : ".");
  }

  async function load() {
    try {
      const response = await fetch(root.dataset.series);
      if (!response.ok) throw new Error(response.status);
      draw(await response.json());
    } catch (e) {
      document.getElementById("charts-note").textContent = "Could not load the curves (" + e + ").";
    }
  }

  window.addEventListener("resize", () => {
    for (const [key, plot] of Object.entries(plots)) {
      plot.setSize({ width: width(root.querySelector(`[data-chart="${key}"]`)), height: 180 });
    }
  });
  load();
  if (root.dataset.live === "true") setInterval(load, 10000);
})();
