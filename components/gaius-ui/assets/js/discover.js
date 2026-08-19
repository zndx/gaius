(function () {
  var qEl = document.getElementById("discover-query");
  var wEl = document.getElementById("discover-window");
  var bEl = document.getElementById("discover-breakdown");
  var histEl = document.getElementById("discover-hist");
  var trendEl = document.getElementById("discover-trends");
  var rowsEl = document.getElementById("discover-rows");
  var countEl = document.getElementById("discover-count");
  var metaEl = document.getElementById("discover-meta");
  var popularEl = document.getElementById("discover-popular");
  var selectedEl = document.getElementById("discover-selected");
  var cdEl = document.getElementById("discover-countdown");
  var timer = null;
  var tick = null;
  var lastEpisode = null;
  var lastLabels = {};

  function esc(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function fmtTs(iso) {
    if (!iso) return "—";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return esc(iso);
    return d.toISOString().replace("T", " ").replace(/\.\d+Z$/, "Z");
  }

  function fmtEta(s) {
    s = Math.max(0, Math.floor(s));
    if (s < 60) return s + "s";
    if (s < 3600) return Math.floor(s / 60) + "m " + (s % 60) + "s";
    var h = Math.floor(s / 3600);
    var m = Math.floor((s % 3600) / 60);
    return h + "h " + m + "m";
  }

  function currentQuery() {
    return (qEl && qEl.value ? qEl.value : "").trim();
  }

  function paintSelected() {
    if (!selectedEl) return;
    var q = currentQuery();
    if (!q) {
      selectedEl.innerHTML = '<span class="muted">none</span>';
      return;
    }
    selectedEl.innerHTML = q
      .split(/\s+/)
      .map(function (tok) {
        var shown = lastLabels[tok] || tok;
        return (
          '<button type="button" class="chip" data-tok="' +
          esc(tok) +
          '" title="' +
          esc(tok) +
          '">' +
          esc(shown) +
          "</button>"
        );
      })
      .join("");
  }

  function paintCountdown(ep, lastAt, clock) {
    if (!cdEl) return;
    lastEpisode = ep;
    if (!ep || !ep.at) {
      cdEl.hidden = true;
      return;
    }
    var eta = ep.eta_s;
    if (ep.at) {
      eta = Math.max(0, Math.round((new Date(ep.at).getTime() - Date.now()) / 1000));
    }
    var last = lastAt ? "Last accrual " + fmtTs(lastAt) : "No tape yet";
    cdEl.hidden = false;
    cdEl.innerHTML =
      '<strong>Next salience:</strong> ' +
      esc(ep.label || ep.kind) +
      " in <span class=\"cd-eta\">" +
      fmtEta(eta) +
      "</span> <span class=\"muted\">(" +
      fmtTs(ep.at) +
      ")</span>" +
      '<span class="cd-last muted"> · ' +
      last +
      "</span>";
  }

  function paintTrends(buckets) {
    if (!trendEl || !buckets.length) {
      if (trendEl) trendEl.innerHTML = "";
      return;
    }
    var w = trendEl.clientWidth || histEl.clientWidth || 600;
    var h = 84;
    trendEl.setAttribute("viewBox", "0 0 " + w + " " + h);
    trendEl.setAttribute("width", "100%");
    trendEl.setAttribute("height", h);
    function series(key) {
      return buckets.map(function (b) {
        return Number(b[key] || 0);
      });
    }
    function line(vals, cls) {
      var max = 0;
      vals.forEach(function (v) {
        if (v > max) max = v;
      });
      if (max <= 0) return "";
      var pts = vals
        .map(function (v, i) {
          var x = (i / Math.max(1, vals.length - 1)) * w;
          var y = h - (v / max) * (h - 4) - 2;
          return x.toFixed(1) + "," + y.toFixed(1);
        })
        .join(" ");
      return '<polyline class="' + cls + '" fill="none" points="' + pts + '" />';
    }
    trendEl.innerHTML =
      line(series("salience_ma"), "tl-sal") +
      line(series("watts_ma"), "tl-w") +
      line(series("util_ma"), "tl-u");
  }

  function paint(data) {
    var buckets = (data && data.buckets) || [];
    var docs = (data && data.docs) || [];
    var facets = (data && data.facets) || [];
    lastLabels = {};
    facets.forEach(function (f) {
      if (f.kind === "feature" && f.label) {
        lastLabels["feature:" + f.key] = f.label;
      }
    });
    var maxS = 1;
    buckets.forEach(function (b) {
      var s = Number(b.salience || b.n || 0);
      if (s > maxS) maxS = s;
    });
    histEl.innerHTML = buckets
      .map(function (b) {
        var s = Number(b.salience || 0);
        var hgt = s > 0 ? Math.max(3, Math.round((s / maxS) * 72)) : 1;
        return (
          '<div class="hist-bar' +
          (s <= 0 ? " empty" : "") +
          '" title="' +
          esc(b.t) +
          " · ev " +
          b.n +
          " · sal " +
          (s ? s.toFixed(1) : "0") +
          " · " +
          Math.round(b.watts || 0) +
          ' W" style="height:' +
          hgt +
          'px"></div>'
        );
      })
      .join("");
    if (!buckets.length) {
      histEl.innerHTML = '<p class="muted">No salience in this window.</p>';
    }
    paintTrends(buckets);
    rowsEl.innerHTML = docs
      .map(function (d) {
        return (
          "<tr>" +
          "<td class=\"mono\">" +
          esc(fmtTs(d.ts)) +
          "</td>" +
          "<td>" +
          esc(d.stream) +
          "</td>" +
          "<td>" +
          esc(d.source) +
          "</td>" +
          "<td><strong>" +
          esc(d.title) +
          "</strong><div class=\"muted\">" +
          esc((d.body || "").slice(0, 180)) +
          "</div></td>" +
          "<td class=\"muted\">—</td>" +
          "</tr>"
        );
      })
      .join("");
    countEl.textContent = "Documents (" + (data.total || 0) + ")";
    metaEl.textContent =
      (data.interval || "") +
      " · " +
      (data.window || "") +
      (data.scraped_at ? " · " + fmtTs(data.scraped_at) : "");
    popularEl.innerHTML = facets
      .map(function (f) {
        var feat = (f.key || "").match(/^(\d+:\d+)/);
        var tok =
          f.kind === "source"
            ? "source:" + f.key
            : f.kind === "feature"
              ? "feature:" + (feat ? feat[1] : f.key)
              : f.kind + ":" + f.key;
        var shown = f.label || f.key;
        return (
          '<button type="button" class="chip" data-add="' +
          esc(tok) +
          '" title="' +
          esc(f.key) +
          '">' +
          esc(shown) +
          " <span class=\"muted\">" +
          f.count +
          "</span></button>"
        );
      })
      .join("");
    if (!facets.length) {
      popularEl.innerHTML = '<span class="muted">No facets yet</span>';
    }
    paintSelected();
    paintCountdown(data.next_episode, data.last_salience_at, data.clock);
  }

  async function load() {
    if (document.hidden) return;
    var windowV = wEl ? wEl.value : "1h";
    var breakdown = bEl ? bEl.value : "source";
    var query = currentQuery();
    var url =
      "/api/gaius/v1/discover?window=" +
      encodeURIComponent(windowV) +
      "&breakdown=" +
      encodeURIComponent(breakdown) +
      "&query=" +
      encodeURIComponent(query) +
      "&limit=50";
    try {
      var r = await fetch(url);
      var data = await r.json();
      if (!r.ok) {
        metaEl.textContent = data.error || r.statusText || "Discover unreachable";
        return;
      }
      if (data.error) {
        metaEl.textContent = data.error;
        return;
      }
      paint(data);
    } catch (e) {
      metaEl.textContent = "Discover unreachable";
    }
  }

  function start() {
    load();
    if (timer) clearInterval(timer);
    timer = setInterval(load, 5000);
    if (tick) clearInterval(tick);
    tick = setInterval(function () {
      if (lastEpisode) paintCountdown(lastEpisode, null, null);
    }, 1000);
  }

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) {
      if (timer) clearInterval(timer);
      timer = null;
      if (tick) clearInterval(tick);
      tick = null;
    } else {
      start();
    }
  });

  var upd = document.getElementById("discover-update");
  if (upd) upd.addEventListener("click", load);
  if (qEl) {
    qEl.addEventListener("keydown", function (e) {
      if (e.key === "Enter") load();
    });
  }
  if (wEl) wEl.addEventListener("change", load);
  if (bEl) bEl.addEventListener("change", load);

  document.addEventListener("click", function (e) {
    var add = e.target.closest("[data-add]");
    if (add && qEl) {
      var tok = add.getAttribute("data-add");
      if (tok && currentQuery().indexOf(tok) === -1) {
        qEl.value = (currentQuery() + " " + tok).trim();
        load();
      }
      return;
    }
    var rem = e.target.closest("[data-tok]");
    if (rem && qEl) {
      var drop = rem.getAttribute("data-tok");
      qEl.value = currentQuery()
        .split(/\s+/)
        .filter(function (t) {
          return t !== drop;
        })
        .join(" ");
      load();
    }
  });

  start();
})();
