/* Shared scale-aware chart math for the Cognition page.
   Ported (MIT) from wxs-agentsview ConcurrencyTimeline geometry:
   true-width buckets positioned by their REAL half-open bounds, a 1/2/5
   "nice" y-axis, and unit-aware tick strategies. Framework-free. */
(function () {
  "use strict";

  /* 1/2/5 x 10^n ladder targeting ~tickTarget intervals, with headroom. */
  function niceScale(maxY, tickTarget) {
    tickTarget = tickTarget || 4;
    if (!isFinite(maxY) || maxY <= 0) return { step: 1, max: 1 };
    var rough = maxY / tickTarget;
    var exp = Math.floor(Math.log10(rough));
    var base = Math.pow(10, exp);
    var normalized = rough / base;
    var mult;
    if (normalized <= 1) mult = 1;
    else if (normalized <= 2) mult = 2;
    else if (normalized <= 5) mult = 5;
    else mult = 10;
    var step = Math.max(mult * base, 1);
    return { step: step, max: Math.ceil(maxY / step) * step };
  }

  /* Observe an element's content width; call cb(width) on change. */
  function observeWidth(el, cb) {
    if (!el || typeof ResizeObserver === "undefined") return null;
    var last = -1;
    var ro = new ResizeObserver(function (entries) {
      var e = entries[0];
      if (!e) return;
      var w = Math.floor(e.contentRect.width);
      if (w !== last && w > 0) {
        last = w;
        cb(w);
      }
    });
    ro.observe(el);
    return ro;
  }

  /* Quantile classifier over the NONZERO values: 0..4 heat levels.
     Quartiles (AgentsView Heatmap server policy) — one outlier no longer
     flattens the scale the way ratio-to-max did. */
  function heatLevels(values) {
    var nz = values.filter(function (v) { return v > 0; }).sort(function (a, b) { return a - b; });
    if (!nz.length) {
      return function () { return 0; };
    }
    function q(p) {
      var i = Math.min(nz.length - 1, Math.floor(p * nz.length));
      return nz[i];
    }
    var q1 = q(0.25), q2 = q(0.5), q3 = q(0.75);
    return function (v) {
      if (!v || v <= 0) return 0;
      if (v <= q1) return 1;
      if (v <= q2) return 2;
      if (v <= q3) return 3;
      return 4;
    };
  }

  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  function pad2(n) { return (n < 10 ? "0" : "") + n; }

  function timeLabel(ms) {
    var d = new Date(ms);
    return pad2(d.getUTCHours()) + ":" + pad2(d.getUTCMinutes());
  }

  function dateLabel(ms) {
    var d = new Date(ms);
    return MONTHS[d.getUTCMonth()] + " " + d.getUTCDate();
  }

  function monthLabel(ms) {
    var d = new Date(ms);
    return MONTHS[d.getUTCMonth()] + " '" + String(d.getUTCFullYear()).slice(2);
  }

  /* Tooltip range label per bucket unit (UTC — the page's stated zone). */
  function rangeLabel(startMs, endMs, unit) {
    if (unit === "hour" || unit === "6h") {
      return dateLabel(startMs) + " " + timeLabel(startMs) + "–" + timeLabel(endMs) + " UTC";
    }
    if (unit === "day") return dateLabel(startMs);
    /* Half-open end: label the last INCLUDED instant. */
    return dateLabel(startMs) + " – " + dateLabel(endMs - 1);
  }

  /* Unit-aware x ticks. hour/6h → five even fractions labeled with real
     UTC times; day → Monday bucket starts; week → 1st-of-month starts;
     month → every bucket start, thinned to ~8 labels. */
  function unitTicks(buckets, unit, rangeStartMs, rangeSpanMs, xForMs) {
    var out = [];
    if (unit === "hour" || unit === "6h") {
      [0, 0.25, 0.5, 0.75, 1].forEach(function (f) {
        var ms = rangeStartMs + f * rangeSpanMs;
        out.push({ x: xForMs(ms), label: timeLabel(ms), edge: f === 0 ? "start" : f === 1 ? "end" : "" });
      });
      return out;
    }
    function boundary(pred, labelFn) {
      buckets.forEach(function (b) {
        if (pred(b.start_ms)) out.push({ x: xForMs(b.start_ms), label: labelFn(b.start_ms), edge: "" });
      });
    }
    if (unit === "day") {
      boundary(function (ms) { return new Date(ms).getUTCDay() === 1; }, dateLabel);
    } else if (unit === "week") {
      boundary(function (ms) { return new Date(ms).getUTCDate() <= 7; }, monthLabel);
    } else {
      var step = Math.max(1, Math.ceil(buckets.length / 8));
      buckets.forEach(function (b, i) {
        if (i % step === 0) out.push({ x: xForMs(b.start_ms), label: monthLabel(b.start_ms), edge: "" });
      });
    }
    return out;
  }

  window.CogChart = {
    niceScale: niceScale,
    observeWidth: observeWidth,
    heatLevels: heatLevels,
    timeLabel: timeLabel,
    dateLabel: dateLabel,
    monthLabel: monthLabel,
    rangeLabel: rangeLabel,
    unitTicks: unitTicks,
  };
})();
