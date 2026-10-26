/* Signal Forge charts.
 *
 * Any element with data-chart="/api/charts/..." becomes a chart that loads
 * that endpoint, redraws it every data-refresh seconds (default 60), and shows
 * the honest freshness line the API returns (as-of date, latency, stale flag).
 * Elements with data-snapshot="fx|crypto" become a refreshing quote table with
 * sparklines. Read-only: no request here changes anything.
 */
(function () {
  "use strict";
  const PALETTE = ["#6366f1", "#10b981", "#f59e0b", "#ef4444", "#06b6d4", "#a855f7", "#84cc16", "#ec4899"];
  const dark = () => window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;

  function theme() {
    const d = dark();
    return {
      layout: { background: { type: "solid", color: "transparent" }, textColor: d ? "#cbd5e1" : "#334155", fontSize: 11 },
      grid: { vertLines: { color: d ? "#1e293b" : "#eef2f7" }, horzLines: { color: d ? "#1e293b" : "#eef2f7" } },
      rightPriceScale: { borderColor: d ? "#334155" : "#e2e8f0" },
      timeScale: { borderColor: d ? "#334155" : "#e2e8f0" },
      crosshair: { mode: 1 },
    };
  }

  function ago(iso) {
    if (!iso) return "never";
    const days = Math.round((Date.now() - new Date(iso + "T00:00:00Z").getTime()) / 86400000);
    if (days <= 0) return "today";
    if (days === 1) return "yesterday";
    return days + " days ago";
  }

  function footer(el, p) {
    let f = el.querySelector(".sf-foot");
    if (!f) {
      f = document.createElement("div");
      f.className = "sf-foot mt-1 flex flex-wrap items-center gap-2 text-[11px] text-slate-500";
      el.appendChild(f);
    }
    const badge = p.stale === true
      ? '<span class="rounded bg-amber-100 px-1.5 text-amber-900">stale</span>'
      : p.stale === false
        ? '<span class="rounded bg-emerald-100 px-1.5 text-emerald-800">current</span>'
        : "";
    const lat = (p.latency || "").replace(/_/g, "-").toLowerCase();
    f.innerHTML =
      (p.as_of ? badge + " latest " + p.as_of + " (" + ago(p.as_of) + ")" : "no data yet") +
      " · " + lat + " · refreshed " + new Date().toLocaleTimeString() +
      (p.note ? ' · <span class="italic">' + p.note + "</span>" : "");
  }

  async function getJSON(url) {
    const r = await fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } });
    if (!r.ok) throw new Error(r.status + " " + url);
    return r.json();
  }

  function mount(el) {
    if (!window.LightweightCharts) return setTimeout(() => mount(el), 150);
    const box = document.createElement("div");
    box.style.height = (el.dataset.height || 320) + "px";
    el.insertBefore(box, el.firstChild);
    const chart = LightweightCharts.createChart(box, Object.assign({ autoSize: true }, theme()));
    let series = [];
    let legend = el.querySelector(".sf-legend");

    async function draw() {
      let p;
      try {
        p = await getJSON(el.dataset.chart);
      } catch (e) {
        footer(el, { note: "could not load (" + e.message + ")", latency: "" });
        return;
      }
      series.forEach((s) => chart.removeSeries(s));
      series = [];
      const names = [];
      p.series.forEach((s, i) => {
        if (!s.data || !s.data.length) return;
        const color = PALETTE[i % PALETTE.length];
        let ser;
        if (s.type === "bars") {
          ser = chart.addHistogramSeries({ color: color, priceFormat: { type: "volume" } });
        } else if (s.type === "candles") {
          ser = chart.addCandlestickSeries({ upColor: "#10b981", downColor: "#ef4444", wickUpColor: "#10b981", wickDownColor: "#ef4444", borderVisible: false });
        } else if (p.series.length === 1) {
          ser = chart.addAreaSeries({ lineColor: color, topColor: color + "55", bottomColor: color + "05", lineWidth: 2 });
        } else {
          ser = chart.addLineSeries({ color, lineWidth: 2, lineStyle: s.name.indexOf("open") >= 0 ? 2 : 0 });
        }
        ser.setData(s.data);
        series.push(ser);
        names.push('<span class="inline-flex items-center gap-1"><i style="background:' + color + '" class="inline-block h-2 w-2 rounded-full"></i>' + s.name + "</span>");
      });
      if (!legend && names.length > 1) {
        legend = document.createElement("div");
        legend.className = "sf-legend mb-1 flex flex-wrap gap-3 text-[11px] text-slate-500";
        el.insertBefore(legend, box);
      }
      if (legend) legend.innerHTML = names.join("");
      let empty = el.querySelector(".sf-empty");
      if (p.empty) {
        if (!empty) {
          empty = document.createElement("div");
          empty.className = "sf-empty pointer-events-none absolute inset-0 flex items-center justify-center text-sm text-slate-400";
          box.style.position = "relative";
          box.appendChild(empty);
        }
        empty.textContent = "Nothing to chart yet" + (p.note ? " — " + p.note : "");
      } else if (empty) {
        empty.remove();
      }
      if (!el.dataset.fitted) { chart.timeScale().fitContent(); el.dataset.fitted = "1"; }
      footer(el, p);
    }
    draw();
    if (el._sfTimer) clearInterval(el._sfTimer);
    el._sfTimer = setInterval(draw, 1000 * Number(el.dataset.refresh || 60));
    window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => chart.applyOptions(theme()));
  }

  function spark(values, up) {
    if (!values || values.length < 2) return "";
    const w = 120, h = 28, lo = Math.min(...values), hi = Math.max(...values), span = hi - lo || 1;
    const pts = values.map((v, i) => (i * w / (values.length - 1)).toFixed(1) + "," + (h - (v - lo) / span * h).toFixed(1)).join(" ");
    return '<svg width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + " " + h + '"><polyline fill="none" stroke="' + (up ? "#10b981" : "#ef4444") + '" stroke-width="1.5" points="' + pts + '"/></svg>';
  }

  function pct(v) {
    if (v === null || v === undefined) return "—";
    const c = v >= 0 ? "text-emerald-600" : "text-red-600";
    return '<span class="' + c + '">' + (v >= 0 ? "+" : "") + v.toFixed(2) + "%</span>";
  }

  function snapshot(el) {
    async function draw() {
      let d;
      try { d = await getJSON("/api/charts/snapshot/" + el.dataset.snapshot); } catch (e) { return; }
      const target = el.dataset.target;
      el.innerHTML =
        '<table class="w-full text-sm"><thead><tr class="text-left text-xs text-slate-500"><th>Pair</th><th class="text-right">Last</th><th class="text-right">1 day</th><th class="text-right">30 days</th><th>60 days</th><th>As of</th></tr></thead><tbody>' +
        d.rows.map((r) =>
          '<tr class="cursor-pointer hover:bg-slate-100 dark:hover:bg-slate-800" data-pair="' + r.pair + '">' +
          '<td class="font-semibold">' + r.pair + "</td>" +
          '<td class="text-right tabular-nums">' + (r.close === null ? "—" : Number(r.close).toLocaleString(undefined, { maximumFractionDigits: 5 })) + "</td>" +
          '<td class="text-right">' + pct(r.chg_1d) + '</td><td class="text-right">' + pct(r.chg_30d) + "</td>" +
          "<td>" + spark(r.spark, (r.chg_30d || 0) >= 0) + "</td>" +
          '<td class="text-xs ' + (r.stale ? "text-amber-600" : "text-slate-500") + '">' + (r.as_of ? ago(r.as_of) : "no data") + "</td></tr>"
        ).join("") + "</tbody></table>";
      if (target) {
        el.querySelectorAll("tr[data-pair]").forEach((tr) => tr.addEventListener("click", () => select(target, tr.dataset.pair)));
      }
    }
    draw();
    setInterval(draw, 60000);
  }

  // A <select data-chart-picker="#chart-id" data-base="/api/charts/fx/"> swaps a chart's source.
  function select(targetSel, value) {
    const el = document.querySelector(targetSel);
    if (!el) return;
    const base = el.dataset.base || "";
    el.dataset.chart = base + encodeURIComponent(value) + (el.dataset.query || "");
    el.dataset.fitted = "";
    el.innerHTML = "";
    const picker = document.querySelector('[data-chart-picker="' + targetSel + '"]');
    if (picker && picker.value !== value) picker.value = value;
    mount(el);
  }

  function init() {
    document.querySelectorAll("[data-chart]").forEach(mount);
    document.querySelectorAll("[data-snapshot]").forEach(snapshot);
    document.querySelectorAll("[data-chart-picker]").forEach((p) =>
      p.addEventListener("change", () => select(p.dataset.chartPicker, p.value)));
    document.querySelectorAll("[data-range]").forEach((b) =>
      b.addEventListener("click", () => {
        const el = document.querySelector(b.dataset.range);
        if (!el) return;
        el.dataset.query = "?days=" + b.dataset.days;
        const cur = el.dataset.chart.split("?")[0];
        el.dataset.chart = cur + el.dataset.query;
        el.dataset.fitted = ""; el.innerHTML = ""; mount(el);
        b.parentElement.querySelectorAll("[data-range]").forEach((x) => x.classList.toggle("bg-indigo-600", x === b));
        b.parentElement.querySelectorAll("[data-range]").forEach((x) => x.classList.toggle("text-white", x === b));
      }));
  }
  document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", init) : init();
})();
