// Curves of one link (uPlot). Data: /api/links/series, refreshed every 10 s
// when the period runs up to now.
(function () {
  "use strict";
  const root = document.getElementById("charts");
  if (!root || typeof uPlot === "undefined") return;
  const css = getComputedStyle(document.documentElement);
  const color = (name) => css.getPropertyValue(name).trim();
  const C = {
    text: color("--muted"), grid: color("--line"), a: color("--accent"),
    b: "#e0a020", c: "#2fbf71", d: "#ff6b6b",
  };
  // Vertical axis: side 3 = left, 1 = right (an undefined side made uPlot draw
  // it as a horizontal axis eating the height of the chart).
  const axis = (label, scale = "y", side = 3) => ({
    label, scale, side, stroke: C.text, grid: { stroke: C.grid, width: 1, show: side === 3 },
    ticks: { stroke: C.grid },
  });
  const series = (label, stroke, scale) => ({ label, stroke, width: 1.5, scale, spanGaps: false });

  const charts = {
    rtt: { series: [series("RTT ms", C.a, "y")], axes: [axis("ms")], data: (d) => [d.rtt_ms] },
    loss: {
      series: [series("loss %", C.d, "y"), series("retrans/s", C.b, "r")],
      axes: [axis("%"), axis("/s", "r", 1)],
      data: (d) => [d.loss_percent, d.retrans_per_s],
    },
    mbps: {
      series: root.dataset.kind === "camera_station"
        ? [series("received Mb/s", C.c, "y")]
        : [series("media server Mb/s", C.a, "y"), series("station Mb/s", C.c, "y")],
      axes: [axis("Mb/s")],
      data: (d) => (root.dataset.kind === "camera_station" ? [d.station_mbps] : [d.mbps, d.station_mbps]),
    },
    fps: {
      series: [series("fps", C.c, "y"), series("decode errors", C.d, "e")],
      axes: [axis("fps"), axis("errors", "e", 1)],
      data: (d) => [d.fps, d.decode_errors],
    },
    dropped: { series: [series("dropped", C.d, "y")], axes: [axis("packets")], data: (d) => [d.dropped] },
  };

  const plots = {};
  function width(el) { return Math.max(300, el.clientWidth); }

  function draw(d) {
    for (const el of root.querySelectorAll("[data-chart]")) {
      const def = charts[el.dataset.chart];
      const data = [d.t, ...def.data(d)];
      const plot = plots[el.dataset.chart];
      if (plot) { plot.setData(data); continue; }
      plots[el.dataset.chart] = new uPlot({
        width: width(el), height: 190,
        scales: { x: { time: true } },
        series: [{}, ...def.series],
        axes: [{ stroke: C.text, grid: { stroke: C.grid, width: 1 }, ticks: { stroke: C.grid } }, ...def.axes],
        legend: { live: true },
      }, data, el);
    }
    const note = document.getElementById("charts-note");
    note.textContent = `${d.t.length} points of ${d.bucket_s} s` + (root.dataset.live === "true" ? " · refreshed every 10 s." : ".");
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
      const el = root.querySelector(`[data-chart="${key}"]`);
      plot.setSize({ width: width(el), height: 190 });
    }
  });
  load();
  if (root.dataset.live === "true") setInterval(load, 10000);
})();
