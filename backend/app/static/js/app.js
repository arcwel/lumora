/* Lumora dashboard — client-side behaviour.
   Two responsibilities:
     1. Render the trend + comparison charts (Chart.js) from the JSON API.
     2. Provide the Alpine `promptTable()` component (client-side sorting).
   Everything degrades gracefully: if the API is empty, charts show an empty
   state instead of erroring. */

(function () {
  "use strict";

  // Muted, professional palette — one hue per provider, assigned stably.
  var PALETTE = [
    "#4f46e5", // indigo
    "#0d9488", // teal
    "#d97706", // amber
    "#db2777", // pink
    "#2563eb", // blue
    "#65a30d", // lime
  ];

  function colorFor(index) {
    return PALETTE[index % PALETTE.length];
  }

  function fmtPct(value) {
    return Math.round(value * 100) + "%";
  }

  function shortLabel(iso) {
    if (!iso) return "—";
    var d = new Date(iso);
    if (isNaN(d)) return "—";
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }

  // Shared Chart.js defaults for a clean, restrained look.
  function applyDefaults() {
    if (!window.Chart) return;
    Chart.defaults.font.family =
      "Inter, ui-sans-serif, system-ui, -apple-system, sans-serif";
    Chart.defaults.font.size = 12;
    Chart.defaults.color = "#94a3b8"; // slate-400
    Chart.defaults.plugins.legend.labels.usePointStyle = true;
    Chart.defaults.plugins.legend.labels.boxWidth = 6;
    Chart.defaults.plugins.legend.labels.boxHeight = 6;
    Chart.defaults.plugins.legend.labels.padding = 16;
  }

  function show(el) { if (el) el.classList.remove("hidden"); el && (el.style.display = "flex"); }

  function fetchJSON(url) {
    return fetch(url, { headers: { Accept: "application/json" } }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }

  function renderTrend(projectId) {
    var canvas = document.getElementById("trendChart");
    if (!canvas) return;
    fetchJSON("/api/projects/" + projectId + "/trends")
      .then(function (data) {
        if (!data.runs.length || !data.series.length) {
          show(document.getElementById("trendEmpty"));
          return;
        }
        var labels = data.runs.map(function (r) { return shortLabel(r.timestamp); });
        var datasets = data.series.map(function (s, i) {
          var c = colorFor(i);
          return {
            label: s.provider,
            data: s.points, // nulls create clean gaps
            borderColor: c,
            backgroundColor: c,
            tension: 0.35,
            borderWidth: 2,
            pointRadius: 2,
            pointHoverRadius: 4,
            spanGaps: true,
          };
        });
        new Chart(canvas, {
          type: "line",
          data: { labels: labels, datasets: datasets },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            scales: {
              y: {
                beginAtZero: true,
                max: 1,
                ticks: { callback: fmtPct, stepSize: 0.25 },
                grid: { color: "#f1f5f9" },
                border: { display: false },
              },
              x: { grid: { display: false }, border: { display: false } },
            },
            plugins: {
              legend: { position: "bottom" },
              tooltip: {
                callbacks: {
                  label: function (ctx) {
                    var v = ctx.parsed.y;
                    return ctx.dataset.label + ": " + (v == null ? "—" : fmtPct(v));
                  },
                },
              },
            },
          },
        });
      })
      .catch(function () { show(document.getElementById("trendEmpty")); });
  }

  function renderComparison(projectId) {
    var canvas = document.getElementById("comparisonChart");
    if (!canvas) return;
    fetchJSON("/api/projects/" + projectId + "/comparison")
      .then(function (data) {
        if (!data.providers.length) {
          show(document.getElementById("comparisonEmpty"));
          return;
        }
        var sorted = data.providers.slice().sort(function (a, b) {
          return b.mention_rate - a.mention_rate;
        });
        new Chart(canvas, {
          type: "bar",
          data: {
            labels: sorted.map(function (p) { return p.provider; }),
            datasets: [
              {
                data: sorted.map(function (p) { return p.mention_rate; }),
                backgroundColor: sorted.map(function (_, i) { return colorFor(i); }),
                borderRadius: 6,
                maxBarThickness: 48,
              },
            ],
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
              y: {
                beginAtZero: true,
                max: 1,
                ticks: { callback: fmtPct, stepSize: 0.25 },
                grid: { color: "#f1f5f9" },
                border: { display: false },
              },
              x: { grid: { display: false }, border: { display: false } },
            },
            plugins: {
              legend: { display: false },
              tooltip: {
                callbacks: {
                  label: function (ctx) { return fmtPct(ctx.parsed.y); },
                },
              },
            },
          },
        });
      })
      .catch(function () { show(document.getElementById("comparisonEmpty")); });
  }

  // Public API used by the project detail template.
  window.Lumora = {
    initCharts: function (projectId) {
      applyDefaults();
      renderTrend(projectId);
      renderComparison(projectId);
    },
  };

  // Alpine component: sortable prompt-performance table.
  window.promptTable = function () {
    return {
      rows: [],
      sort: { key: "mention_rate", dir: "desc" },
      load: function () {
        var el = document.getElementById("prompt-data");
        try {
          this.rows = el ? JSON.parse(el.textContent) : [];
        } catch (e) {
          this.rows = [];
        }
      },
      sortBy: function (key) {
        if (this.sort.key === key) {
          this.sort.dir = this.sort.dir === "desc" ? "asc" : "desc";
        } else {
          this.sort.key = key;
          this.sort.dir = key === "text" ? "asc" : "desc";
        }
      },
      get sortedRows() {
        var key = this.sort.key;
        var dir = this.sort.dir === "desc" ? -1 : 1;
        return this.rows.slice().sort(function (a, b) {
          var av = a[key];
          var bv = b[key];
          if (key === "mention_rate") {
            // Null rates (no data) always sort to the bottom.
            av = av == null ? -1 : av;
            bv = bv == null ? -1 : bv;
            return (av - bv) * dir;
          }
          av = (av || "").toString().toLowerCase();
          bv = (bv || "").toString().toLowerCase();
          return av < bv ? -1 * dir : av > bv ? 1 * dir : 0;
        });
      },
    };
  };
})();
