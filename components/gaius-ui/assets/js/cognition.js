(function () {
  var WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

  function $(id) {
    return document.getElementById(id);
  }

  function params() {
    var q = new URLSearchParams(location.search);
    return {
      window_days: parseInt(($("cog-window") && $("cog-window").value) || q.get("window_days") || "365", 10),
      stream: ($("cog-stream") && $("cog-stream").value) || q.get("stream") || "",
    };
  }

  function writeUrl(p) {
    var q = new URLSearchParams();
    if (p.window_days && p.window_days !== 365) q.set("window_days", String(p.window_days));
    if (p.stream) q.set("stream", p.stream);
    var s = q.toString();
    history.replaceState(null, "", s ? (location.pathname + "?" + s) : location.pathname);
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

  function heatClass(n, max) {
    if (!n || max <= 0) return "cog-h0";
    var t = n / max;
    if (t > 0.75) return "cog-h4";
    if (t > 0.5) return "cog-h3";
    if (t > 0.25) return "cog-h2";
    return "cog-h1";
  }

  function fmtNum(n) {
    if (n == null) return "—";
    return Number(n).toLocaleString();
  }

  function fmtPct(n) {
    if (!n) return "—";
    return (Math.round(n * 10) / 10).toFixed(1) + "%";
  }

  function paintStats(data) {
    var cards = [
      [fmtNum(data.thoughts), "Thoughts", ""],
      [fmtNum(data.cycles_in_window), "Cycles", "lifetime " + fmtNum(data.cycles_completed)],
      [fmtNum(data.streams), "Streams", "thought types"],
      [fmtNum(data.active_days), "Active days", "UTC"],
      [
        data.thoughts_per_cycle ? data.thoughts_per_cycle.toFixed(1) : "—",
        "Thoughts/cycle",
        "",
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
        (c[2] ? '<div class="muted cog-stat-sub">' + c[2] + "</div>" : "");
      el.appendChild(div);
    });
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
      var href = thoughtHref(t);
      var li = document.createElement("li");
      li.className = "cog-rail-item";
      if (href) {
        li.innerHTML =
          '<a class="cog-rail-link" href=""></a>' +
          '<div class="cog-rail-meta">' +
          '<span class="cog-type"></span>' +
          '<span class="muted"></span>' +
          "</div>";
        var a = li.querySelector(".cog-rail-link");
        a.href = href;
        a.textContent = t.title || "(untitled)";
      } else {
        li.innerHTML =
          '<div class="cog-rail-title"></div>' +
          '<div class="cog-rail-meta">' +
          '<span class="cog-type"></span>' +
          '<span class="muted"></span>' +
          "</div>";
        li.querySelector(".cog-rail-title").textContent = t.title || "(untitled)";
      }
      li.querySelector(".cog-type").textContent = (t.thought_type || "—").toUpperCase();
      li.querySelector(".muted").textContent = relTime(t.timestamp_ms);
      if (t.summary) li.title = t.summary;
      list.appendChild(li);
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

  function mondayUTC(d) {
    var x = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
    var dow = x.getUTCDay();
    var back = dow === 0 ? 6 : dow - 1;
    x.setUTCDate(x.getUTCDate() - back);
    return x;
  }

  function isoDay(d) {
    return d.toISOString().slice(0, 10);
  }

  function paintYear(data, windowDays) {
    var host = $("cog-year");
    host.replaceChildren();
    var byDay = {};
    var max = 0;
    (data.days || []).forEach(function (d) {
      byDay[d.date] = d.thoughts;
      if (d.thoughts > max) max = d.thoughts;
    });
    var end = new Date();
    var start = new Date();
    start.setUTCDate(start.getUTCDate() - (windowDays - 1));
    var cursor = mondayUTC(start);
    var endMon = mondayUTC(end);
    var weeks = document.createElement("div");
    weeks.className = "cog-year-weeks";
    while (cursor <= endMon) {
      var col = document.createElement("div");
      col.className = "cog-year-col";
      for (var i = 0; i < 7; i++) {
        var cell = document.createElement("span");
        var day = new Date(cursor);
        day.setUTCDate(cursor.getUTCDate() + i);
        var key = isoDay(day);
        var n = byDay[key] || 0;
        var inWin = day >= start && day <= end;
        cell.className = "cog-cell " + (inWin ? heatClass(n, max) : "cog-hoff");
        cell.title = key + " · " + n + " thoughts";
        col.appendChild(cell);
      }
      weeks.appendChild(col);
      cursor.setUTCDate(cursor.getUTCDate() + 7);
    }
    var labels = document.createElement("div");
    labels.className = "cog-year-dows";
    ["Mon", "", "Wed", "", "Fri", "", ""].forEach(function (lab) {
      var s = document.createElement("span");
      s.textContent = lab;
      labels.appendChild(s);
    });
    host.appendChild(labels);
    host.appendChild(weeks);
  }

  function paintBars(data, windowDays) {
    var host = $("cog-bars");
    host.replaceChildren();
    var byDay = {};
    var max = 1;
    (data.days || []).forEach(function (d) {
      byDay[d.date] = d.thoughts;
      if (d.thoughts > max) max = d.thoughts;
    });
    var span = Math.min(windowDays, 42);
    var end = new Date();
    for (var i = span - 1; i >= 0; i--) {
      var d = new Date();
      d.setUTCDate(end.getUTCDate() - i);
      var key = isoDay(d);
      var n = byDay[key] || 0;
      var bar = document.createElement("div");
      bar.className = "cog-bar";
      var fill = document.createElement("div");
      fill.className = "cog-bar-fill";
      fill.style.height = Math.max(2, Math.round((n / max) * 100)) + "%";
      bar.appendChild(fill);
      bar.title = key + " · " + n;
      host.appendChild(bar);
    }
  }

  function paintHow(data) {
    var host = $("cog-how");
    host.replaceChildren();
    var max = 0;
    var map = {};
    (data.hours || []).forEach(function (h) {
      map[h.weekday + ":" + h.hour] = h.thoughts;
      if (h.thoughts > max) max = h.thoughts;
    });
    var table = document.createElement("div");
    table.className = "cog-how-grid";
    var head = document.createElement("div");
    head.className = "cog-how-row";
    head.appendChild(document.createElement("span"));
    for (var hr = 0; hr < 24; hr++) {
      var hs = document.createElement("span");
      hs.className = "cog-how-h";
      hs.textContent = hr % 3 === 0 ? String(hr) : "";
      head.appendChild(hs);
    }
    table.appendChild(head);
    for (var wd = 0; wd < 7; wd++) {
      var row = document.createElement("div");
      row.className = "cog-how-row";
      var lab = document.createElement("span");
      lab.className = "cog-how-lab";
      lab.textContent = WEEKDAYS[wd];
      row.appendChild(lab);
      for (var hour = 0; hour < 24; hour++) {
        var cell = document.createElement("span");
        var n = map[wd + ":" + hour] || 0;
        cell.className = "cog-cell " + heatClass(n, max);
        cell.title = WEEKDAYS[wd] + " " + hour + "h · " + n;
        row.appendChild(cell);
      }
      table.appendChild(row);
    }
    host.appendChild(table);
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
      var href = thoughtHref(t);
      var li = document.createElement("li");
      li.className = "cog-top-item";
      li.innerHTML =
        '<span class="cog-top-n"></span>' +
        '<div class="cog-top-body">' +
        (href
          ? '<a class="cog-top-title cog-top-link" href=""></a>'
          : '<div class="cog-top-title"></div>') +
        '<div class="muted cog-top-sub"></div>' +
        "</div>" +
        '<span class="cog-top-score mono"></span>';
      li.querySelector(".cog-top-n").textContent = String(i + 1);
      var titleEl = li.querySelector(".cog-top-title");
      titleEl.textContent = t.title || "(untitled)";
      if (href) titleEl.setAttribute("href", href);
      li.querySelector(".cog-top-sub").textContent =
        (t.thought_type || "—") + (t.summary ? " · " + t.summary : "");
      li.querySelector(".cog-top-score").textContent = t.salience
        ? t.salience.toFixed(2)
        : "—";
      host.appendChild(li);
    });
  }

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

  function load() {
    var p = params();
    writeUrl(p);
    var url =
      "/api/gaius/v1/cognition?window_days=" +
      encodeURIComponent(p.window_days) +
      "&stream=" +
      encodeURIComponent(p.stream);
    return fetch(url).then(function (r) {
      return r.text().then(function (text) {
        if (!r.ok) {
          throw new Error(text || "cognition " + r.status);
        }
        return JSON.parse(text);
      });
    }).then(function (data) {
      showError("");
      paintChrome(data);
      paintStats(data);
      paintRail(data);
      paintYear(data, p.window_days);
      paintBars(data, p.window_days);
      paintHow(data);
      paintTop(data);
      if (window.GaiusSurface) {
        window.GaiusSurface.setPage("/cognition");
        window.GaiusSurface.setNearby(
          (data.recent || []).slice(0, 12).map(function (t) {
            return { kind: t.thought_type || "thought", title: t.title };
          })
        );
      }
    }).catch(function (err) {
      showError(String(err.message || err));
    });
  }

  function boot() {
    var q = new URLSearchParams(location.search);
    var w = q.get("window_days");
    if (w && $("cog-window")) $("cog-window").value = w;
    if ($("cog-refresh")) $("cog-refresh").addEventListener("click", load);
    if ($("cog-window")) $("cog-window").addEventListener("change", load);
    if ($("cog-stream")) $("cog-stream").addEventListener("change", load);
    load();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
