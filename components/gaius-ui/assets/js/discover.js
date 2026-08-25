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
  var timer = null;
  var tick = null;
  var lastStatus = null;
  var lastLabels = {};
  var inflight = false;
  var engineLive = false;
  var wfTimer = null;
  var wfSeen = 0;
  var wfWindow = 60;
  var lastWfEpoch = 0;
  var wfReady = false;
  var wfGeom = null;
  var wfWinEl = document.getElementById("discover-wf-window");

  function wfWindowS() {
    var n = wfWinEl ? parseInt(wfWinEl.value, 10) : 60;
    return n > 0 ? n : 60;
  }

  function wfPollMs() {
    return wfWindowS() > 60 ? 5000 : 100;
  }

  function cacheKey() {
    return (
      "gaius-discover:" +
      (wEl ? wEl.value : "1h") +
      ":" +
      currentQuery()
    );
  }

  function readCache() {
    try {
      var raw = sessionStorage.getItem(cacheKey());
      return raw ? JSON.parse(raw) : null;
    } catch (e) {
      return null;
    }
  }

  function writeCache(data) {
    try {
      sessionStorage.setItem(cacheKey(), JSON.stringify(data));
    } catch (e) {}
  }

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

  function fmtHms(s) {
    s = Math.max(0, Math.floor(s));
    var h = Math.floor(s / 3600);
    var m = Math.floor((s % 3600) / 60);
    var sec = s % 60;
    function pad(n) {
      return (n < 10 ? "0" : "") + n;
    }
    return pad(h) + ":" + pad(m) + ":" + pad(sec);
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

  function paintStrip(st, connected) {
    lastStatus = st || lastStatus;
    var eng = document.getElementById("stat-engine");
    var wattsEl = document.getElementById("stat-watts");
    var art = document.getElementById("stat-articles");
    var proj = document.getElementById("stat-projects");
    var th = document.getElementById("stat-thoughts");
    if (art && st) art.textContent = String(st.articles || 0);
    if (proj && st) proj.textContent = String(st.projects || 0);
    if (th && st) th.textContent = String(st.thoughts || 0);
    var termsEl = document.getElementById("stat-terms");
    var agendaEl = document.getElementById("stat-agenda");
    var thetaEl = document.getElementById("stat-theta");
    if (termsEl) {
      termsEl.textContent = st
        ? "Terms: " + (st.terms_skos || 0) + " / " + (st.terms_cites || 0)
        : "Terms: —";
    }
    if (agendaEl) {
      agendaEl.textContent = st
        ? "Agenda: " +
          Number(st.agenda_min || 0).toFixed(0) +
          " / " +
          Number(st.agenda_max || 0).toFixed(0) +
          " / " +
          Number(st.agenda_std || 0).toFixed(1)
        : "Agenda: —";
    }
    if (thetaEl) {
      thetaEl.textContent = st
        ? "Theta: " +
          Number(st.salience_peak || 0).toFixed(1) +
          " / " +
          (st.cognition_tokens || 0)
        : "Theta: —";
    }
    if (wattsEl) {
      var live = st && st.watts_live;
      var w = st && typeof st.watts === "number" ? st.watts : null;
      wattsEl.textContent =
        live && w != null ? "Watts: " + Math.round(w) : "Watts: —";
    }
    if (!eng) return;
    if (!connected) {
      eng.innerHTML = '<span class="pill warn">connecting…</span>';
      return;
    }
    if (st && st.updating) {
      eng.innerHTML =
        '<span class="kumo-spin" aria-hidden="true"></span>' +
        '<span class="pill warn">Updating</span>';
      return;
    }
    var n = st ? Number(st.workflows || 0) : 0;
    if (n > 0) {
      eng.innerHTML =
        '<span class="kumo-spin" aria-hidden="true"></span>' +
        "Workflows: " +
        n;
      return;
    }
    var waitAt = st && st.waiting_at;
    if (waitAt) {
      var eta = Math.max(
        0,
        Math.round((new Date(waitAt).getTime() - Date.now()) / 1000)
      );
      eng.textContent = "Waiting: " + fmtHms(eta);
      return;
    }
    eng.innerHTML = '<span class="pill ok">connected</span>';
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
      var s = Number(b.salience || 0);
      if (s <= 0) s = Number(b.watts || 0);
      if (s > maxS) maxS = s;
    });
    histEl.innerHTML = buckets
      .map(function (b) {
        var s = Number(b.salience || 0);
        if (s <= 0) s = Number(b.watts || 0);
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
    if (!docs.length) {
      rowsEl.innerHTML =
        '<tr><td colspan="5" class="muted">No inflow in this window.</td></tr>';
    } else {
    rowsEl.innerHTML = docs
      .map(function (d) {
        var open =
          "/summary?section=corpus&open=" +
          encodeURIComponent("corpus/inflow/" + (d.source_id || ""));
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
          "<td><a class=\"discover-open\" href=\"" +
          esc(open) +
          "\"><strong>" +
          esc(d.title) +
          "</strong></a><div class=\"muted\">" +
          esc((d.body || "").slice(0, 180)) +
          "</div></td>" +
          "<td class=\"muted\">—</td>" +
          "</tr>"
        );
      })
      .join("");
    }
    countEl.textContent =
      "Documents (" +
      (docs.length || data.total || 0) +
      ")" +
      (data.total === 0 && docs.length
        ? " · latest (none in window)"
        : "");
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
    engineLive = true;
    paintStrip(data.status, true);
  }

  async function load() {
    if (document.hidden || inflight) return;
    inflight = true;
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
    var ctrl = new AbortController();
    var to = setTimeout(function () {
      ctrl.abort();
    }, 4000);
    try {
      var r = await fetch(url, { signal: ctrl.signal });
      var data = await r.json();
      if (!r.ok) {
        metaEl.textContent = data.error || r.statusText || "Discover unreachable";
        if (!engineLive) paintStrip(null, false);
        return;
      }
      if (data.error) {
        metaEl.textContent = data.error;
        if (!engineLive) paintStrip(null, false);
        return;
      }
      writeCache(data);
      paint(data);
    } catch (e) {
      var cached = readCache();
      if (cached) {
        paint(cached);
        if (metaEl) metaEl.textContent = (metaEl.textContent || "") + " · cached";
      } else if (metaEl) {
        metaEl.textContent = "Discover unreachable";
        paintStrip(null, false);
      }
    } finally {
      clearTimeout(to);
      inflight = false;
    }
  }

  function clip01(x) {
    if (x < 0) return 0;
    if (x > 1) return 1;
    return x;
  }

  var DKCYAN2 = [
    [
      [0xd3, 0xd3, 0xd3],
      [0x9e, 0xb9, 0xa4],
      [0x69, 0x9e, 0x74],
    ],
    [
      [0x9a, 0xa5, 0xbb],
      [0x73, 0x90, 0x91],
      [0x4c, 0x7c, 0x67],
    ],
    [
      [0x62, 0x77, 0xa5],
      [0x4a, 0x68, 0x80],
      [0x31, 0x59, 0x5b],
    ],
  ];
  var RAMP_POS = [
    [252, 187, 161],
    [252, 146, 114],
    [251, 106, 74],
    [222, 45, 38],
    [165, 15, 21],
  ];
  var RAMP_NEG = [
    [158, 202, 225],
    [107, 174, 214],
    [66, 146, 198],
    [33, 113, 181],
    [8, 69, 148],
  ];

  function lerp3(a, b, t) {
    return [
      Math.round(a[0] + (b[0] - a[0]) * t),
      Math.round(a[1] + (b[1] - a[1]) * t),
      Math.round(a[2] + (b[2] - a[2]) * t),
    ];
  }

  function dkcyan2(power, util) {
    var x = clip01(power) * 2;
    var y = clip01(util) * 2;
    var i0 = Math.min(1, Math.floor(x));
    var j0 = Math.min(1, Math.floor(y));
    var tx = x - i0;
    var ty = y - j0;
    var c00 = DKCYAN2[i0][j0];
    var c10 = DKCYAN2[i0 + 1][j0];
    var c01 = DKCYAN2[i0][j0 + 1];
    var c11 = DKCYAN2[i0 + 1][j0 + 1];
    return lerp3(lerp3(c00, c10, tx), lerp3(c01, c11, tx), ty);
  }

  function onsetField(values) {
    var n = values.length;
    var e = new Array(n);
    var i;
    for (i = 0; i < n; i++) e[i] = 0;
    var prevDv = 0;
    for (i = 1; i < n; i++) {
      var dv = values[i] - values[i - 1];
      var d2 = dv - prevDv;
      prevDv = dv;
      var sharp = clip01(Math.abs(d2));
      var peak = Math.abs(dv) * (1 + 0.55 * sharp);
      var spread = Math.abs(dv) * 1.05 * (1 - 0.4 * sharp);
      var sign = dv >= 0 ? 1 : -1;
      function acc(j, mag) {
        var s = sign * mag;
        var cur = e[j];
        if (cur * s >= 0) {
          e[j] = Math.abs(s) >= Math.abs(cur) ? cur + s : cur + 0.35 * s;
        } else {
          e[j] = Math.abs(s) >= Math.abs(cur) ? s : cur;
        }
      }
      acc(i, peak);
      acc(i - 1, spread);
      if (i + 1 < n) acc(i + 1, spread);
    }
    return e;
  }

  function highpass(values, alpha) {
    alpha = alpha === undefined ? 0.12 : alpha;
    var ema = values.length ? values[0] : 0;
    var out = [];
    var i;
    for (i = 0; i < values.length; i++) {
      var v = values[i];
      ema = ema + alpha * (v - ema);
      out.push(v - ema);
    }
    return out;
  }

  function flashRgb(energy) {
    var a = Math.max(0, Math.abs(energy) - 0.02);
    var t = clip01(a / 1.15);
    var stops = energy >= 0 ? RAMP_POS : RAMP_NEG;
    var x = t * (stops.length - 1);
    var i = Math.min(stops.length - 2, Math.floor(x));
    return lerp3(stops[i], stops[i + 1], x - i);
  }

  function motionMix(energy) {
    var a = Math.max(0, Math.abs(energy) - 0.025);
    return clip01(1 - Math.exp(-1.65 * a));
  }

  function overlayMotion(rgb, d) {
    var a = motionMix(d);
    if (a <= 0) return rgb;
    return lerp3(rgb, flashRgb(d), a);
  }

  function unpackGpu(x) {
    if (!(x > 0.5)) return { p: 0, u: 0, on: false };
    var t = x - 1;
    if (t < 0) t = 0;
    var u = Math.floor(t * 10000 + 1e-9) / 10000;
    if (u > 1) u = 1;
    var p01 = (t - u) * 10000;
    if (p01 < 0) p01 = 0;
    if (p01 > 1) p01 = 1;
    return { p: p01 * 2 - 1, u: u, on: true };
  }

  function gpuRgb(power, util, prevP, prevU) {
    var base = dkcyan2(clip01(power), clip01(util));
    if (prevP === undefined || prevU === undefined) return base;
    var dp = power - prevP;
    var du = util - prevU;
    var d = Math.abs(dp) >= Math.abs(du) ? dp : du;
    return overlayMotion(base, d);
  }

  function signedRgb(v, prev) {
    var mag = clip01(Math.abs(v));
    var base = dkcyan2(mag, mag);
    var d = prev === undefined ? v : v - prev;
    return overlayMotion(base, d);
  }

  function stripRgb(name, amp, prevAmp) {
    if (name && name.indexOf("gpu-") === 0) {
      var un = unpackGpu(typeof amp === "number" ? amp : 0);
      var pv =
        prevAmp === undefined ? undefined : unpackGpu(typeof prevAmp === "number" ? prevAmp : 0);
      if (!un.on) return dkcyan2(0, 0);
      if (!pv || !pv.on) return gpuRgb(un.p, un.u);
      return gpuRgb(un.p, un.u, pv.p, pv.u);
    }
    return signedRgb(
      typeof amp === "number" ? amp : 0,
      prevAmp === undefined ? undefined : prevAmp
    );
  }

  function paintWaterfall(data) {
    var canvas = document.getElementById("discover-waterfall");
    if (!canvas || !data || !data.matrix) return false;
    var C = data.n_channels | 0;
    var T = data.n_times | 0;
    if (C < 1 || T < 1) return false;
    wfWindow = T;
    var names = data.channel_names || [];
    var dpr = window.devicePixelRatio || 1;
    var cssW = canvas.clientWidth || 920;
    var cssH = canvas.clientHeight || 200;
    var W = Math.max(1, Math.floor(cssW * dpr));
    var H = Math.max(1, Math.floor(cssH * dpr));
    var labelW = names.length ? Math.round(56 * dpr) : 0;
    var rasterW = Math.max(1, W - labelW);
    var colW = rasterW / T;
    var rowH = H / C;
    var ctx = canvas.getContext("2d");
    var resized = canvas.width !== W || canvas.height !== H;
    if (resized) {
      canvas.width = W;
      canvas.height = H;
    }
    ctx.imageSmoothingEnabled = false;
    var colors = [];
    var ry, x;
    for (ry = 0; ry < C; ry++) {
      var nm = names[ry] || "";
      var rowC = [];
      if (nm.indexOf("gpu-") === 0) {
        var pw = [];
        var ut = [];
        for (x = 0; x < T; x++) {
          var un = unpackGpu(data.matrix[ry * T + x]);
          pw.push(un.on ? un.p : 0);
          ut.push(un.on ? un.u : 0);
        }
        var ep = onsetField(pw);
        var eu = onsetField(ut);
        var hpP = highpass(pw);
        var hpU = highpass(ut);
        for (x = 0; x < T; x++) {
          /* pw is signed [-1,1]; occupancy is [0,1]. clip01(signed) zeros idle. */
          var pVis = clip01(
            0.45 * clip01((pw[x] + 1) * 0.5) + 0.9 * Math.abs(hpP[x])
          );
          var uVis = clip01(0.45 * clip01(ut[x]) + 0.9 * Math.abs(hpU[x]));
          var e = Math.abs(ep[x]) >= Math.abs(eu[x]) ? ep[x] : eu[x];
          rowC[x] = overlayMotion(dkcyan2(pVis, uVis), e);
        }
      } else {
        var vals = [];
        for (x = 0; x < T; x++) vals.push(Number(data.matrix[ry * T + x]) || 0);
        var ev = onsetField(vals);
        for (x = 0; x < T; x++) {
          var mag = clip01(Math.abs(vals[x]));
          rowC[x] = overlayMotion(dkcyan2(mag, mag), ev[x]);
        }
      }
      colors[ry] = rowC;
    }
    var cs = getComputedStyle(document.documentElement);
    var bgHex = (cs.getPropertyValue("--color-kumo-base") || "#101418").trim() || "#101418";
    var bg = [16, 20, 24];
    if (bgHex.charAt(0) === "#" && bgHex.length >= 7) {
      bg = [
        parseInt(bgHex.slice(1, 3), 16),
        parseInt(bgHex.slice(3, 5), 16),
        parseInt(bgHex.slice(5, 7), 16),
      ];
    }
    var img = ctx.createImageData(W, H);
    var buf = img.data;
    var pi;
    for (pi = 0; pi < buf.length; pi += 4) {
      buf[pi] = bg[0];
      buf[pi + 1] = bg[1];
      buf[pi + 2] = bg[2];
      buf[pi + 3] = 255;
    }
    var py, px;
    for (py = 0; py < H; py++) {
      var y = Math.min(C - 1, Math.floor(py / rowH));
      var rowCols = colors[y];
      if (!rowCols) continue;
      for (px = labelW; px < W; px++) {
        var s = (px - labelW) / colW;
        if (s < 0) s = 0;
        var x0 = Math.min(T - 1, Math.max(0, Math.floor(s)));
        var x1 = Math.min(T - 1, x0 + 1);
        var fx = s - x0;
        var c0 = rowCols[x0];
        var c1 = rowCols[x1];
        var off = (py * W + px) * 4;
        buf[off] = Math.round(c0[0] + (c1[0] - c0[0]) * fx);
        buf[off + 1] = Math.round(c0[1] + (c1[1] - c0[1]) * fx);
        buf[off + 2] = Math.round(c0[2] + (c1[2] - c0[2]) * fx);
        buf[off + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
    if (labelW) {
      var fg = (cs.getPropertyValue("--text-color-kumo-subtle") || "#9fa5ac").trim();
      ctx.fillStyle = "rgb(" + bg[0] + "," + bg[1] + "," + bg[2] + ")";
      ctx.fillRect(0, 0, labelW, H);
      ctx.textBaseline = "middle";
      ctx.textAlign = "right";
      ctx.fillStyle = fg || "#9fa5ac";
      ctx.font =
        Math.max(8, Math.floor(Math.min(11 * dpr, rowH * 0.78))) +
        "px ui-monospace, monospace";
      for (var ly = 0; ly < C; ly++) {
        ctx.fillText(
          names[ly] || String(ly),
          labelW - 4 * dpr,
          ly * rowH + rowH / 2,
          labelW - 6 * dpr
        );
      }
    }
    wfGeom = { C: C, T: T, W: W, H: H, labelW: labelW };
    wfReady = true;
    return true;
  }

  var wfInflight = false;
  function loadWaterfall() {
    if (document.hidden || wfInflight) return;
    wfInflight = true;
    fetch("/api/gaius/v1/cognition/waterfall?window_s=" + wfWindowS())
      .then(function (r) {
        return r.text().then(function (text) {
          if (!r.ok) throw new Error(text || "waterfall " + r.status);
          return JSON.parse(text);
        });
      })
      .then(function (data) {
        if (data && data.error) throw new Error(data.error);
        var ep = Number(data.epoch_unix_ms || 0);
        if (ep && ep !== lastWfEpoch) {
          lastWfEpoch = ep;
          var shifted = paintWaterfall(data);
          if (shifted) {
            wfSeen += 1;
            if (wfWindow > 0 && wfSeen % wfWindow === 0) load();
          }
        }
      })
      .catch(function (err) {
        if (wfWindowS() > 60 && metaEl) {
          metaEl.textContent = String((err && err.message) || err);
        }
      })
      .finally(function () {
        wfInflight = false;
      });
  }

  function start() {
    var cached = readCache();
    if (cached) paint(cached);
    else if (metaEl) metaEl.textContent = "Loading…";
    load();
    if (timer) clearInterval(timer);
    timer = setInterval(load, 5000);
    if (tick) clearInterval(tick);
    tick = setInterval(function () {
      if (engineLive && lastStatus && !lastStatus.updating) {
        paintStrip(lastStatus, true);
      }
    }, 1000);
    if (wfTimer) clearInterval(wfTimer);
    wfTimer = setInterval(loadWaterfall, wfPollMs());
    loadWaterfall();
  }

  if (wfWinEl) {
    wfWinEl.addEventListener("change", function () {
      lastWfEpoch = 0;
      if (wfTimer) clearInterval(wfTimer);
      wfTimer = setInterval(loadWaterfall, wfPollMs());
      loadWaterfall();
    });
  }

  function resetStripTheme() {
    wfReady = false;
    wfGeom = null;
  }
  document.addEventListener("gaius-mode", function () {
    resetStripTheme();
    loadWaterfall();
  });
  try {
    new MutationObserver(function () {
      resetStripTheme();
    }).observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-mode"],
    });
  } catch (e) {}

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) {
      if (timer) clearInterval(timer);
      timer = null;
      if (tick) clearInterval(tick);
      tick = null;
      if (wfTimer) clearInterval(wfTimer);
      wfTimer = null;
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
