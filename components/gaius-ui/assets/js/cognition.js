(function () {
  var CC = window.CogChart;

  function $(id) {
    return document.getElementById(id);
  }

  /* ── URL / params (minimal-URL; defaults omitted; from/to = brush) ────── */

  var DEFAULT_WINDOW = "365d";
  var range = { from: 0, to: 0 }; // brush selection (ms); 0 = none

  function legacyWindow(days) {
    var n = parseInt(days, 10);
    if (!n) return "";
    if (n <= 1) return "24h";
    return n + "d";
  }

  function params() {
    var q = new URLSearchParams(location.search);
    return {
      window:
        ($("cog-win") && $("cog-win").value) ||
        q.get("window") ||
        legacyWindow(q.get("window_days")) ||
        DEFAULT_WINDOW,
      bucket: ($("cog-bucket") && $("cog-bucket").value) || q.get("bucket") || "",
      stream: ($("cog-stream") && $("cog-stream").value) || q.get("stream") || "",
    };
  }

  function writeUrl(p) {
    var q = new URLSearchParams();
    if (p.window && p.window !== DEFAULT_WINDOW) q.set("window", p.window);
    if (p.bucket) q.set("bucket", p.bucket);
    if (p.stream) q.set("stream", p.stream);
    if (range.from && range.to) {
      q.set("from", String(range.from));
      q.set("to", String(range.to));
    }
    var s = q.toString();
    var next = s ? location.pathname + "?" + s : location.pathname;
    if (next !== location.pathname + location.search) {
      history.pushState(null, "", next);
    }
  }

  function hydrateControls() {
    var q = new URLSearchParams(location.search);
    var w = q.get("window") || legacyWindow(q.get("window_days")) || DEFAULT_WINDOW;
    if ($("cog-win")) $("cog-win").value = w;
    if ($("cog-bucket")) $("cog-bucket").value = q.get("bucket") || "";
    range.from = parseInt(q.get("from") || "0", 10) || 0;
    range.to = parseInt(q.get("to") || "0", 10) || 0;
    paintRangeChip();
  }

  function paintRangeChip() {
    var chip = $("cog-range-chip");
    if (!chip) return;
    if (range.from && range.to) {
      chip.hidden = false;
      chip.textContent =
        CC.dateLabel(range.from) + " " + CC.timeLabel(range.from) +
        " – " + CC.dateLabel(range.to) + " " + CC.timeLabel(range.to) + " ✕";
    } else {
      chip.hidden = true;
    }
  }

  function thoughtHref(t) {
    if (!t || !t.id) return "";
    return "/summary?lens=thoughts&open=" + encodeURIComponent("thought/" + t.id);
  }

  function relTime(ms) {
    if (!ms) return "—";
    var d = Date.now() - ms;
    if (d < 0) d = 0;
    var m = Math.floor(d / 60000);
    if (m < 1) return "just now";
    if (m < 60) return m + "m ago";
    var h = Math.floor(m / 60);
    if (h < 48) return h + "h ago";
    var days = Math.floor(h / 24);
    return days + "d ago";
  }

  function fmtNum(n) {
    if (n == null) return "—";
    return Number(n).toLocaleString();
  }

  function fmtPct(n) {
    if (!n) return "—";
    return (Math.round(n * 10) / 10).toFixed(1) + "%";
  }

  /* ── Stats + rail + top ──────────────────────────────────────────────── */

  function paintStats(data) {
    var cards = [
      [fmtNum(data.thoughts), "Thoughts", ""],
      [fmtNum(data.cycles_in_window), "Cycles", "lifetime " + fmtNum(data.cycles_completed)],
      [fmtNum(data.streams), "Streams", "thought types"],
      [fmtNum(data.active_days), "Active days", "UTC"],
      [
        data.thoughts_per_cycle ? data.thoughts_per_cycle.toFixed(1) : "—",
        "Thoughts/cycle",
        data.current_task ? "task: " + data.current_task : "",
      ],
      [
        fmtPct(data.concentration_pct),
        "Concentration",
        data.concentration_stream || "—",
      ],
    ];
    var el = $("cog-stats");
    el.replaceChildren();
    cards.forEach(function (c) {
      var div = document.createElement("div");
      div.className = "landing-stat";
      div.innerHTML =
        '<div class="landing-stat-value">' +
        c[0] +
        '</div><div class="landing-stat-label">' +
        c[1] +
        "</div>" +
        (c[2] ? '<div class="muted cog-stat-sub"></div>' : "");
      if (c[2]) div.querySelector(".cog-stat-sub").textContent = c[2];
      el.appendChild(div);
    });
  }

  function railItem(t, live) {
    var li = document.createElement("li");
    li.className = "cog-rail-item" + (live ? " cog-live-new" : "");
    li.dataset.id = t.id || t.thought_id || "";
    li.innerHTML =
      '<div class="cog-rail-title"></div>' +
      '<div class="cog-rail-meta">' +
      '<span class="cog-type"></span>' +
      '<span class="muted"></span>' +
      "</div>";
    li.querySelector(".cog-rail-title").textContent = t.title || "(untitled)";
    li.querySelector(".cog-type").textContent = (t.thought_type || "—").toUpperCase();
    li.querySelector(".muted").textContent = relTime(t.timestamp_ms);
    if (t.summary) li.title = t.summary;
    li.style.cursor = "pointer";
    return li;
  }

  function paintRail(data) {
    var count = $("cog-rail-count");
    if (count) count.textContent = fmtNum(data.thoughts) + " THOUGHTS";
    var sel = $("cog-stream");
    var current = (sel && sel.value) || params().stream || "";
    if (sel) {
      sel.replaceChildren();
      var all = document.createElement("option");
      all.value = "";
      all.textContent = "All streams";
      sel.appendChild(all);
      (data.stream_counts || []).forEach(function (s) {
        var o = document.createElement("option");
        o.value = s.id;
        o.textContent = s.id + " · " + s.thoughts;
        if (s.id === current) o.selected = true;
        sel.appendChild(o);
      });
      if (current && !sel.value) sel.value = "";
    }
    var list = $("cog-rail-list");
    list.replaceChildren();
    var items = data.recent || [];
    if (!items.length) {
      var empty = document.createElement("li");
      empty.className = "cog-rail-empty muted";
      empty.textContent = "No thoughts in this window.";
      list.appendChild(empty);
    }
    items.forEach(function (t) {
      list.appendChild(railItem(t, false));
    });
    var foot = $("cog-rail-foot");
    if (foot) {
      foot.textContent =
        "federation.project=" +
        (data.project || "gaius") +
        " · " +
        fmtNum(data.thoughts) +
        " thoughts · " +
        fmtNum(data.streams) +
        " streams";
    }
  }

  function paintTop(data) {
    var host = $("cog-top");
    host.replaceChildren();
    var items = data.top || [];
    if (!items.length) {
      var li = document.createElement("li");
      li.className = "muted";
      li.textContent = "No thoughts to rank.";
      host.appendChild(li);
      return;
    }
    items.forEach(function (t, i) {
      var li = document.createElement("li");
      li.className = "cog-top-item";
      li.dataset.id = t.id || "";
      li.style.cursor = "pointer";
      li.innerHTML =
        '<span class="cog-top-n"></span>' +
        '<div class="cog-top-body">' +
        '<div class="cog-top-title"></div>' +
        '<div class="muted cog-top-sub"></div>' +
        "</div>" +
        '<span class="cog-top-score mono"></span>';
      li.querySelector(".cog-top-n").textContent = String(i + 1);
      li.querySelector(".cog-top-title").textContent = t.title || "(untitled)";
      li.querySelector(".cog-top-sub").textContent =
        (t.thought_type || "—") + (t.summary ? " · " + t.summary : "");
      li.querySelector(".cog-top-score").textContent = t.salience
        ? t.salience.toFixed(2)
        : "—";
      host.appendChild(li);
    });
  }

  /* ── Thought drawer (full content + ancestor chain) ──────────────────── */

  function closeDrawer() {
    var root = $("cog-drawer-root");
    if (root) root.replaceChildren();
  }

  function metaRow(dl, label, value) {
    if (value === "" || value == null) return;
    var dt = document.createElement("dt");
    dt.textContent = label;
    var dd = document.createElement("dd");
    dd.textContent = String(value);
    dl.appendChild(dt);
    dl.appendChild(dd);
  }

  function openDrawer(id) {
    if (!id) return;
    fetch("/api/gaius/v1/cognition/thought?id=" + encodeURIComponent(id))
      .then(function (r) {
        return r.text().then(function (text) {
          if (!r.ok) throw new Error(text || "thought " + r.status);
          return JSON.parse(text);
        });
      })
      .then(function (data) {
        var t = data.thought;
        if (!t) throw new Error("thought missing");
        var root = $("cog-drawer-root");
        root.replaceChildren();
        var backdrop = document.createElement("div");
        backdrop.className = "cog-drawer-backdrop";
        backdrop.addEventListener("click", closeDrawer);
        var drawer = document.createElement("aside");
        drawer.className = "cog-drawer";
        drawer.setAttribute("role", "dialog");
        drawer.innerHTML =
          '<div class="cog-drawer-head">' +
          '<span class="cog-type"></span>' +
          '<span class="cog-drawer-title"></span>' +
          '<button type="button" class="cog-drawer-close" aria-label="Close">✕</button>' +
          "</div>" +
          '<div class="cog-drawer-body">' +
          '<dl class="cog-drawer-meta"></dl>' +
          '<div class="cog-drawer-content"></div>' +
          '<div class="cog-drawer-links"></div>' +
          '<h4 class="muted">Chain</h4><div class="cog-drawer-chain"></div>' +
          "</div>";
        drawer.querySelector(".cog-type").textContent = (t.thought_type || "—").toUpperCase();
        drawer.querySelector(".cog-drawer-title").textContent = t.title || "(untitled)";
        drawer.querySelector(".cog-drawer-close").addEventListener("click", closeDrawer);
        var dl = drawer.querySelector(".cog-drawer-meta");
        metaRow(dl, "salience", t.salience != null ? t.salience.toFixed(2) : "");
        metaRow(dl, "confidence", t.confidence ? t.confidence.toFixed(2) : "");
        metaRow(dl, "novelty", t.novelty ? t.novelty.toFixed(2) : "");
        metaRow(dl, "status", t.status);
        metaRow(dl, "generation", t.generation);
        metaRow(dl, "tokens", t.tokens_used ? fmtNum(t.tokens_used) : "");
        metaRow(dl, "model", t.generator_model);
        metaRow(dl, "when", relTime(t.timestamp_ms));
        metaRow(dl, "domains", (t.domains || []).join(", "));
        drawer.querySelector(".cog-drawer-content").textContent =
          t.content || t.summary || "(no content)";
        var links = drawer.querySelector(".cog-drawer-links");
        var a = document.createElement("a");
        a.className = "cog-chip";
        a.href = thoughtHref(t);
        a.textContent = "Open in Summary →";
        links.appendChild(a);
        var chainHost = drawer.querySelector(".cog-drawer-chain");
        var chain = data.chain || [];
        if (chain.length <= 1) {
          var none = document.createElement("div");
          none.className = "muted";
          none.textContent = "No predecessors.";
          chainHost.appendChild(none);
        } else {
          chain.forEach(function (c) {
            var row = document.createElement("div");
            row.className = "cog-chain-item" + (c.id === t.id ? " current" : "");
            if (c.id === t.id) {
              row.textContent = "g" + c.generation + " · " + (c.title || c.id);
            } else {
              var link = document.createElement("a");
              link.href = "#";
              link.textContent = "g" + c.generation + " · " + (c.title || c.id);
              link.addEventListener("click", function (ev) {
                ev.preventDefault();
                openDrawer(c.id);
              });
              row.appendChild(link);
            }
            chainHost.appendChild(row);
          });
        }
        root.appendChild(backdrop);
        root.appendChild(drawer);
      })
      .catch(function (err) {
        showError(String(err.message || err));
      });
  }

  /* ── Contributions calendar — always 2D (7 dow rows × week columns) ────
     AgentsView Heatmap.svelte pattern: the calendar is DAILY regardless of
     the Activity chart's bucket grain. When the surface answered at a
     coarser grain (week/month), refetch the SAME range at bucket=day; only
     if the server degrades day away (>MAX_BUCKETS span) fall back to the
     honest 1-row strip. Sunday-start columns, Mon/Wed/Fri row labels,
     month labels above, fluid cellStep across the full panel width. */

  var MONTHS_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var CAL_DOW_W = 26; /* .cog-year-dows fixed width (px), synced with CSS */
  var calCache = { key: "", data: null };

  function paintCalendar(data, hostWidth) {
    var panel = $("cog-calendar-panel");
    var host = $("cog-year");
    if (!panel || !host) return;
    var buckets = data.buckets || [];
    var unit = data.interval;
    /* meta first, so the readout survives empty windows */
    var meta = $("cog-cal-meta");
    if (meta) {
      var asOf = data.effective_end_ms
        ? new Date(data.effective_end_ms).toISOString().slice(0, 16).replace("T", " ") + "Z"
        : "";
      meta.textContent =
        (unit || "?") + " buckets · " + buckets.length +
        (asOf ? " · as of " + asOf : "") + " · UTC";
    }
    if (!buckets.length) {
      panel.hidden = true;
      return;
    }
    panel.hidden = false;
    if (unit === "hour" || unit === "6h") {
      /* sub-day windows: bucket strip (still brushable via data-s/e) */
      renderStrip(host, buckets, unit, hostWidth);
      return;
    }
    if (unit === "day") {
      renderYearGrid(host, buckets, data, hostWidth);
      return;
    }
    /* coarser grain: fetch daily cells for the same range + filters */
    var q = new URLSearchParams();
    if (range.from && range.to) {
      q.set("from_ms", String(range.from));
      q.set("to_ms", String(range.to));
    } else {
      q.set("window", params().window);
    }
    if (params().stream) q.set("stream", params().stream);
    q.set("bucket", "day");
    var key = q.toString();
    if (calCache.key === key && calCache.data) {
      renderYearGrid(host, calCache.data.buckets, calCache.data, hostWidth);
      return;
    }
    var version = loadVersion;
    fetch("/api/gaius/v1/cognition?" + key)
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (day) {
        if (version !== loadVersion) return;
        if (day && day.interval === "day" && (day.buckets || []).length) {
          calCache = { key: key, data: day };
          renderYearGrid(host, day.buckets, day, hostWidth);
        } else {
          /* server degraded day away (range too wide) — honest strip */
          renderStrip(host, buckets, unit, hostWidth);
        }
      })
      .catch(function () { renderStrip(host, buckets, unit, hostWidth); });
  }

  function renderStrip(host, buckets, unit, hostWidth) {
    host.replaceChildren();
    var level = CC.heatLevels(buckets.map(function (b) { return b.thoughts; }));
    var width = Math.max(hostWidth || host.clientWidth || 600, 220);
    var step = Math.min(24, Math.max(6, (width - 8) / buckets.length));
    var strip = document.createElement("div");
    strip.className = "cog-strip";
    buckets.forEach(function (b) {
      var cell = document.createElement("span");
      cell.className = "cog-cell cog-h" + level(b.thoughts);
      cell.style.width = step - 3 + "px";
      cell.style.height = "16px";
      cell.title = CC.rangeLabel(b.start_ms, b.end_ms, unit) + " · " + b.thoughts + " thoughts";
      cell.dataset.s = String(b.start_ms);
      cell.dataset.e = String(b.end_ms);
      strip.appendChild(cell);
    });
    host.appendChild(strip);
  }

  function renderYearGrid(host, buckets, meta, hostWidth) {
    host.replaceChildren();
    var level = CC.heatLevels(buckets.map(function (b) { return b.thoughts; }));
    var byDay = {};
    buckets.forEach(function (b) {
      byDay[new Date(b.start_ms).toISOString().slice(0, 10)] = b.thoughts;
    });
    var start = new Date(meta.range_start_ms);
    var end = new Date(meta.range_end_ms - 1);
    var cursor = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth(), start.getUTCDate()));
    cursor.setUTCDate(cursor.getUTCDate() - cursor.getUTCDay()); /* back to Sunday */
    var cols = Math.ceil((end - cursor) / (7 * 86400000));
    var width = Math.max(hostWidth || host.clientWidth || 600, 220);
    var budget = width - CAL_DOW_W - 12;
    var cellStep = Math.min(18, Math.max(3, budget / cols));
    var gapPx = Math.min(3, Math.max(1, Math.round(cellStep * 0.18)));
    var cellPx = Math.max(2, Math.floor(cellStep - gapPx));
    var stepPx = cellPx + gapPx;
    host.style.setProperty("--cog-cell", cellPx + "px");
    host.style.setProperty("--cog-gap", gapPx + "px");

    /* month labels row (AgentsView: label where a new month lands in rows ≤3) */
    var months = document.createElement("div");
    months.className = "cog-year-months";
    var row = document.createElement("div");
    row.className = "cog-year-row";
    var labels = document.createElement("div");
    labels.className = "cog-year-dows";
    ["", "Mon", "", "Wed", "", "Fri", ""].forEach(function (lab) {
      var s = document.createElement("span");
      s.textContent = lab;
      labels.appendChild(s);
    });
    var weeks = document.createElement("div");
    weeks.className = "cog-year-weeks";
    var lastMonth = -1;
    var colIdx = 0;
    while (cursor <= end) {
      var col = document.createElement("div");
      col.className = "cog-year-col";
      for (var i = 0; i < 7; i++) {
        var cell = document.createElement("span");
        var day = new Date(cursor);
        day.setUTCDate(cursor.getUTCDate() + i);
        var key = day.toISOString().slice(0, 10);
        var n = byDay[key] || 0;
        var inWin = day >= start && day <= end;
        cell.className = "cog-cell " + (inWin ? "cog-h" + level(n) : "cog-hoff");
        cell.title = key + " · " + n + " thoughts";
        if (inWin) {
          var dayMs = Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate());
          cell.dataset.s = String(dayMs);
          cell.dataset.e = String(dayMs + 86400000);
        }
        if (inWin && i <= 3 && day.getUTCMonth() !== lastMonth) {
          if (lastMonth !== -1 && cellStep >= 4) {
            var m = document.createElement("span");
            m.textContent = MONTHS_SHORT[day.getUTCMonth()];
            m.style.left = colIdx * stepPx + "px";
            months.appendChild(m);
          }
          lastMonth = day.getUTCMonth();
        }
        col.appendChild(cell);
      }
      weeks.appendChild(col);
      cursor.setUTCDate(cursor.getUTCDate() + 7);
      colIdx++;
    }
    row.appendChild(labels);
    row.appendChild(weeks);
    host.appendChild(months);
    host.appendChild(row);
  }

  /* ── Contributions — by Source and Workflow (federated contract) ──────
     Rows come from data.contributions: local systems of record today
     (gaius.activity / gaius.openlineage); federated systems over the
     signals protocol (Atlas+OpenLineage, Metaflow, Airflow) are PENDING
     and will arrive peer/system-stamped through the same shape. */

  var CONTRIB_MAX_ROWS = 6;   /* AgentsView MAX_SERIES */
  var CONTRIB_MAX_STRIP = 64; /* per-row strip only when buckets fit */

  function contribSection(host, label, items, data) {
    var h = document.createElement("div");
    h.className = "cog-contrib-h mono muted";
    h.textContent = label;
    host.appendChild(h);
    if (!items.length) {
      var none = document.createElement("div");
      none.className = "muted cog-empty";
      none.textContent = "No " + label.toLowerCase() + " in this window.";
      host.appendChild(none);
      return;
    }
    var buckets = data.buckets || [];
    var shown = items.slice(0, CONTRIB_MAX_ROWS);
    var rest = items.slice(CONTRIB_MAX_ROWS);
    if (rest.length) {
      var other = {
        id: "Other (" + rest.length + ")",
        system: "",
        total: 0,
        series: new Array(buckets.length).fill(0),
        other: true,
      };
      rest.forEach(function (c) {
        other.total += c.total || 0;
        (c.series || []).forEach(function (v, i) { other.series[i] += v; });
      });
      shown.push(other);
    }
    var max = shown.reduce(function (m, c) { return Math.max(m, c.total || 0); }, 1);
    shown.forEach(function (c) {
      var row = document.createElement("div");
      row.className = "cog-contrib-row" + (c.other ? " cog-contrib-other" : "");
      var name = document.createElement("span");
      name.className = "cog-contrib-name mono";
      name.textContent = c.id;
      name.title = c.id + (c.system ? " · " + c.system + " · " + (c.peer || "gaius") : "");
      var track = document.createElement("span");
      track.className = "cog-contrib-track";
      var bar = document.createElement("span");
      bar.className = "cog-contrib-bar";
      bar.style.width = ((c.total / max) * 100).toFixed(1) + "%";
      track.appendChild(bar);
      var n = document.createElement("span");
      n.className = "cog-contrib-n mono muted";
      n.textContent = fmtNum(c.total);
      row.appendChild(name);
      row.appendChild(track);
      row.appendChild(n);
      if (buckets.length && buckets.length <= CONTRIB_MAX_STRIP && !c.other) {
        var level = CC.heatLevels(c.series || []);
        var strip = document.createElement("span");
        strip.className = "cog-contrib-strip";
        (c.series || []).forEach(function (v, i) {
          var cell = document.createElement("span");
          cell.className = "cog-cell cog-h" + level(v);
          cell.title =
            CC.rangeLabel(buckets[i].start_ms, buckets[i].end_ms, data.interval) + " · " + v;
          strip.appendChild(cell);
        });
        row.appendChild(strip);
      }
      host.appendChild(row);
    });
  }

  function paintContributions(data) {
    var host = $("cog-contrib");
    if (!host) return;
    host.replaceChildren();
    var items = data.contributions || [];
    contribSection(host, "SOURCES", items.filter(function (c) { return c.group === "source"; }), data);
    contribSection(host, "WORKFLOWS", items.filter(function (c) { return c.group === "workflow"; }), data);
  }

  /* ── Calendar brush — range authoring on the Activity heatmap ────────── */

  function attachCalendarBrush() {
    var host = $("cog-year");
    if (!host) return;
    var anchor = null;
    host.style.touchAction = "none";
    function cellAt(ev) {
      var el = document.elementFromPoint(ev.clientX, ev.clientY);
      return el && el.closest ? el.closest("[data-s]") : null;
    }
    function mark(lo, hi) {
      host.querySelectorAll("[data-s]").forEach(function (c) {
        var s = +c.dataset.s;
        c.classList.toggle("cog-cell-sel", s >= lo && s < hi);
      });
    }
    host.addEventListener("pointerdown", function (ev) {
      var c = cellAt(ev);
      if (!c) return;
      anchor = { s: +c.dataset.s, e: +c.dataset.e };
      try { host.setPointerCapture(ev.pointerId); } catch (e) { /* noop */ }
      mark(anchor.s, anchor.e);
    });
    host.addEventListener("pointermove", function (ev) {
      if (!anchor) return;
      var c = cellAt(ev);
      if (c) mark(Math.min(anchor.s, +c.dataset.s), Math.max(anchor.e, +c.dataset.e));
    });
    host.addEventListener("pointerup", function (ev) {
      if (!anchor) return;
      var c = cellAt(ev);
      var s = anchor.s;
      var e = anchor.e;
      if (c) {
        s = Math.min(s, +c.dataset.s);
        e = Math.max(e, +c.dataset.e);
      }
      host.querySelectorAll(".cog-cell-sel").forEach(function (x) {
        x.classList.remove("cog-cell-sel");
      });
      anchor = null;
      range.from = s; /* click w/o drag = single-cell range */
      range.to = e;
      paintRangeChip();
      load();
    });
  }

  /* ── Federation lanes (self + peers answering kind=COGNITION) ────────── */

  function fedSpark(buckets) {
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "cog-fed-spark");
    svg.setAttribute("viewBox", "0 0 120 16");
    svg.setAttribute("preserveAspectRatio", "none");
    var max = 0;
    buckets.forEach(function (b) { if (b.thoughts > max) max = b.thoughts; });
    if (!max) return svg;
    var n = buckets.length;
    var bw = 120 / n;
    buckets.forEach(function (b, i) {
      if (!b.thoughts) return;
      var h = Math.max(1.5, (b.thoughts / max) * 15);
      var r = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      r.setAttribute("x", (i * bw).toFixed(2));
      r.setAttribute("y", (16 - h).toFixed(2));
      r.setAttribute("width", Math.max(bw - 0.6, 0.6).toFixed(2));
      r.setAttribute("height", h.toFixed(2));
      svg.appendChild(r);
    });
    return svg;
  }

  function paintFederation(data) {
    var panel = $("cog-fed-panel");
    var host = $("cog-fed");
    if (!panel || !host) return;
    var items = (data && data.items) || [];
    if (!items.length) {
      panel.hidden = true;
      return;
    }
    panel.hidden = false;
    host.replaceChildren();
    items.forEach(function (it) {
      var lane = document.createElement("div");
      lane.className = "cog-fed-lane" + (it.project === "gaius" ? " self" : "");
      var chip = document.createElement("span");
      chip.className = "cog-fed-chip mono";
      chip.textContent = it.project;
      var dot = document.createElement("span");
      dot.className = "cog-live-dot" + (it.running ? " on" : "");
      dot.title = it.running ? "running" : "stopped";
      var counts = document.createElement("span");
      counts.className = "muted mono cog-fed-counts";
      counts.textContent =
        it.thoughts + " thoughts · " + it.cycles + " cycles" +
        (it.interval ? " · " + it.interval : "");
      lane.appendChild(chip);
      lane.appendChild(dot);
      lane.appendChild(fedSpark(it.buckets || []));
      lane.appendChild(counts);
      if (it.last_cycle_ms) {
        var last = document.createElement("span");
        last.className = "muted cog-fed-last";
        last.textContent = "last cycle " + relTime(it.last_cycle_ms);
        lane.appendChild(last);
      }
      host.appendChild(lane);
    });
    var meta = $("cog-fed-meta");
    if (meta) meta.textContent = items.length + " engine" + (items.length === 1 ? "" : "s") + " · ~30d · absent peers are honest absences";
  }

  function loadFederation() {
    fetch("/api/gaius/v1/federation/cognition")
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) { if (data) paintFederation(data); })
      .catch(function () {});
  }

  /* ── Reasoning corpus (hx.cot_reasoning — traces are the product) ────── */

  function corpusRow(it) {
    var row = document.createElement("div");
    row.className = "cog-corpus-row";
    row.dataset.traceId = it.id;
    var top = document.createElement("div");
    top.className = "cog-corpus-top";
    var subj = document.createElement("strong");
    subj.textContent = it.subject || "(no subject)";
    top.appendChild(subj);
    if (it.has_layers) {
      var badge = document.createElement("span");
      badge.className = "cog-corpus-badge";
      badge.textContent = it.layer_count + " layers";
      badge.title = "dual-constraint reasoning_layers retained";
      top.appendChild(badge);
    }
    var when = document.createElement("span");
    when.className = "muted cog-corpus-when";
    when.textContent = relTime(it.generated_at_ms);
    top.appendChild(when);
    var sub = document.createElement("div");
    sub.className = "muted mono cog-corpus-sub";
    sub.textContent =
      it.flow_name + "/" + it.step_name + " · run " + it.run_id +
      " · " + it.technique + " · " + it.model_name +
      " · " + it.output_tokens + " tok" +
      (it.latency_ms ? " · " + (it.latency_ms / 1000).toFixed(1) + "s" : "");
    row.appendChild(top);
    row.appendChild(sub);
    return row;
  }

  function paintCorpus(data) {
    var panel = $("cog-corpus-panel");
    var host = $("cog-corpus");
    if (!panel || !host) return;
    var items = (data && data.items) || [];
    if (!items.length) {
      panel.hidden = true;
      return;
    }
    panel.hidden = false;
    host.replaceChildren();
    items.forEach(function (it) { host.appendChild(corpusRow(it)); });
    var meta = $("cog-corpus-meta");
    if (meta)
      meta.textContent =
        items.length + " of " + data.total + " traces · 30d · hx.cot_reasoning";
  }

  function loadCorpus() {
    fetch("/api/gaius/v1/cognition/corpus?limit=20&window_days=30")
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) { if (data) paintCorpus(data); })
      .catch(function () {});
  }

  function traceSection(parent, label, text, mono) {
    if (!text) return;
    var h = document.createElement("div");
    h.className = "cog-trace-h mono muted";
    h.textContent = label;
    var pre = document.createElement("pre");
    pre.className = "cog-drawer-content" + (mono ? " mono" : "");
    pre.textContent = text;
    parent.appendChild(h);
    parent.appendChild(pre);
  }

  function openTraceDrawer(id) {
    if (!id) return;
    fetch("/api/gaius/v1/cognition/trace?id=" + encodeURIComponent(id))
      .then(function (r) {
        return r.text().then(function (text) {
          if (!r.ok) throw new Error(text || "trace " + r.status);
          return JSON.parse(text);
        });
      })
      .then(function (data) {
        var it = data.item || {};
        var root = $("cog-drawer-root");
        root.replaceChildren();
        var backdrop = document.createElement("div");
        backdrop.className = "cog-drawer-backdrop";
        backdrop.addEventListener("click", closeDrawer);
        var drawer = document.createElement("aside");
        drawer.className = "cog-drawer";
        drawer.setAttribute("role", "dialog");
        var head = document.createElement("div");
        head.className = "cog-drawer-head";
        var type = document.createElement("span");
        type.className = "cog-type";
        type.textContent = "trace";
        var title = document.createElement("span");
        title.className = "cog-drawer-title";
        title.textContent = it.subject || id;
        var close = document.createElement("button");
        close.type = "button";
        close.className = "cog-drawer-close";
        close.setAttribute("aria-label", "Close");
        close.textContent = "✕";
        close.addEventListener("click", closeDrawer);
        head.appendChild(type);
        head.appendChild(title);
        head.appendChild(close);
        drawer.appendChild(head);
        var body = document.createElement("div");
        body.className = "cog-drawer-body";
        var dl = document.createElement("dl");
        dl.className = "cog-drawer-meta";
        metaRow(dl, "flow", it.flow_name + "/" + it.step_name);
        metaRow(dl, "run", it.run_id);
        metaRow(dl, "product", it.product_id);
        metaRow(dl, "technique", it.technique);
        metaRow(dl, "model", it.model_name);
        metaRow(dl, "decision", it.decision);
        metaRow(dl, "confidence", it.confidence ? it.confidence.toFixed(2) : "");
        metaRow(dl, "tokens", it.input_tokens + " in · " + it.output_tokens + " out");
        metaRow(dl, "latency", it.latency_ms ? (it.latency_ms / 1000).toFixed(1) + "s" : "");
        metaRow(dl, "generated", it.generated_at_ms ? new Date(it.generated_at_ms).toISOString() : "");
        body.appendChild(dl);
        (data.layers || []).forEach(function (l) {
          traceSection(
            body,
            "LAYER " + l.layer + " · " + (l.producer || "?") +
              (l.tokens ? " · " + l.tokens + " tok" : "") +
              " · " + l.text.length + " ch",
            l.text,
            false
          );
        });
        traceSection(body, "REASONING TRACE · " + (data.reasoning_trace || "").length + " ch", data.reasoning_trace, false);
        traceSection(body, "DECISION OUTPUT", data.output, true);
        drawer.appendChild(body);
        root.appendChild(backdrop);
        root.appendChild(drawer);
      })
      .catch(function (err) { showError(String(err.message || err)); });
  }

  /* ── Chrome, errors ──────────────────────────────────────────────────── */

  function paintChrome(data) {
    var run = $("cog-running");
    if (run) {
      run.textContent = data.running ? "RUNNING" : "STOPPED";
      run.className = "pill " + (data.running ? "ok" : "warn");
    }
    var upd = $("cog-updated");
    if (upd) {
      var extra = data.last_cycle_timestamp_ms
        ? " · last cycle " + relTime(data.last_cycle_timestamp_ms)
        : "";
      upd.textContent = "Updated just now · UTC" + extra;
    }
  }

  function showError(msg) {
    var el = $("cog-error");
    if (!el) return;
    el.hidden = !msg;
    el.textContent = msg || "";
  }

  /* ── Live SSE ticker (SubscribeCognition bridge) ─────────────────────── */

  var THOUGHT_TYPES = {
    thought: 1, pattern: 1, connection: 1, curiosity: 1,
    self_observation: 1, engine_audit: 1,
  };

  function startEvents() {
    if (typeof EventSource === "undefined") return;
    var dot = $("cog-live");
    var es = new EventSource("/api/gaius/v1/cognition/events");
    es.addEventListener("open", function () {
      if (dot) dot.classList.add("on");
    });
    es.addEventListener("error", function () {
      if (dot) dot.classList.remove("on");
      /* EventSource auto-reconnects; the 60s poll below covers the gap. */
    });
    es.addEventListener("cognition", function (msg) {
      var ev;
      try {
        ev = JSON.parse(msg.data);
      } catch (e) {
        return;
      }
      if (THOUGHT_TYPES[ev.type] && ev.thought_id) {
        var list = $("cog-rail-list");
        if (list) {
          var emptyRow = list.querySelector(".cog-rail-empty");
          if (emptyRow) emptyRow.remove();
          list.prepend(
            railItem(
              {
                id: ev.thought_id,
                title: ev.title,
                thought_type: ev.thought_type,
                summary: ev.summary,
                timestamp_ms: ev.timestamp_ms,
              },
              true
            )
          );
        }
      } else if (ev.type === "cycle_end") {
        load(false); /* refresh panels once a cycle lands */
      }
    });
  }

  /* ── Load + resize + history ─────────────────────────────────────────── */

  var lastData = null;
  var loadVersion = 0;

  function paintAll(data) {
    paintChrome(data);
    paintStats(data);
    paintRail(data);
    paintCalendar(data, $("cog-year") ? $("cog-year").clientWidth : 0);
    paintContributions(data);
    paintTop(data);
    if (window.GaiusSurface) {
      window.GaiusSurface.setPage("/cognition");
      window.GaiusSurface.setNearby(
        (data.recent || []).slice(0, 12).map(function (t) {
          return { kind: t.thought_type || "thought", title: t.title };
        })
      );
    }
  }

  function load(pushHistory) {
    var p = params();
    if (pushHistory !== false) writeUrl(p);
    var version = ++loadVersion;
    var q = new URLSearchParams();
    if (range.from && range.to) {
      q.set("from_ms", String(range.from));
      q.set("to_ms", String(range.to));
      if (p.bucket) q.set("bucket", p.bucket);
    } else {
      q.set("window", p.window);
      if (p.bucket) q.set("bucket", p.bucket);
    }
    if (p.stream) q.set("stream", p.stream);
    return fetch("/api/gaius/v1/cognition?" + q.toString())
      .then(function (r) {
        return r.text().then(function (text) {
          if (!r.ok) throw new Error(text || "cognition " + r.status);
          return JSON.parse(text);
        });
      })
      .then(function (data) {
        if (version !== loadVersion) return;
        lastData = data;
        showError("");
        paintAll(data);
      })
      .catch(function (err) {
        if (version !== loadVersion) return;
        showError(String(err.message || err));
      });
  }

  function boot() {
    hydrateControls();
    var q = new URLSearchParams(location.search);
    if (q.get("stream") && $("cog-stream")) {
      var o = document.createElement("option");
      o.value = q.get("stream");
      o.selected = true;
      $("cog-stream").appendChild(o);
    }
    if ($("cog-refresh")) $("cog-refresh").addEventListener("click", function () { load(); });
    ["cog-win", "cog-bucket", "cog-stream"].forEach(function (id) {
      if ($(id))
        $(id).addEventListener("change", function () {
          range.from = 0;
          range.to = 0;
          paintRangeChip();
          load();
        });
    });
    if ($("cog-range-chip"))
      $("cog-range-chip").addEventListener("click", function () {
        range.from = 0;
        range.to = 0;
        paintRangeChip();
        load();
      });
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") closeDrawer();
    });
    /* delegated drawer opens from rail + top lists */
    ["cog-rail-list", "cog-top"].forEach(function (id) {
      var el = $(id);
      if (!el) return;
      el.addEventListener("click", function (ev) {
        var li = ev.target.closest("[data-id]");
        if (li && li.dataset.id) {
          ev.preventDefault();
          openDrawer(li.dataset.id);
        }
      });
    });
    window.addEventListener("popstate", function () {
      hydrateControls();
      load(false);
    });
    if (CC && $("cog-calendar-panel")) {
      CC.observeWidth($("cog-calendar-panel"), function () {
        if (lastData) {
          paintCalendar(lastData, $("cog-year") ? $("cog-year").clientWidth : 0);
        }
      });
    }
    attachCalendarBrush();
    startEvents();
    loadFederation();
    loadCorpus();
    var corpus = $("cog-corpus");
    if (corpus)
      corpus.addEventListener("click", function (ev) {
        var row = ev.target.closest("[data-trace-id]");
        if (row) openTraceDrawer(row.dataset.traceId);
      });
    setInterval(function () {
      if (document.visibilityState === "visible") {
        loadFederation();
        loadCorpus();
      }
    }, 120000);
    setInterval(function () {
      if (document.visibilityState === "visible") load(false);
    }, 60000);
    load(false);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
