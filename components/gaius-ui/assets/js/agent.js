(function () {
  var SYSTEM =
    "You are the Gaius Ask panel. You see the current web UI through " +
    "the Surface context the client attaches. When the user says this, " +
    "here, or the event, they mean Focus if it is set. Use Focus body " +
    "and Clock as facts. Do not invent warehouses, flights, or times " +
    "that are not in Surface. To create or change Agenda items, hand " +
    "off to thinking (:::gaius-handoff) — do not write the card in prose. " +
    "For a stock candlestick, emit " +
    ":::gaius-artifact {\"type\":\"ohlc\",\"symbol\":\"TICKER\"} " +
    "with TICKER from the user message, or call gaius__ask_present. " +
    "Do not invent OHLC bars or substitute another ticker. " +
    "You have your own Complete loop (interpretable/SAE), independent of " +
    "Terminal thinking. When asked about Terminal — metrics, telemetry, " +
    "exchanges, logs, what thinking is doing — use Surface.ops. Do not wait " +
    "for thinking to finish. Reply in concise markdown. You are served by Gaius Engine/Complete.";

  var history = [];
  var busy = false;
  var currentLive = null;

  window.GaiusSurface = window.GaiusSurface || {
    page: location.pathname,
    focus: null,
    nearby: [],
  };

  function $(id) {
    return document.getElementById(id);
  }

  function setOpen(on) {
    var panel = $("ask-panel");
    var btn = $("ask-toggle");
    if (!panel) return;
    panel.hidden = !on;
    document.body.classList.toggle("ask-open", on);
    if (btn) {
      btn.classList.toggle("active", on);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
    }
    try {
      if (on) localStorage.setItem("gaius-ask-open", "1");
      else localStorage.removeItem("gaius-ask-open");
    } catch (e) {}
    paintContext();
    if (on && $("ask-input")) $("ask-input").focus();
  }

  function isOpen() {
    var panel = $("ask-panel");
    return panel && !panel.hidden;
  }

  function basename(p) {
    return String(p || "").split("/").pop() || "";
  }

  function paintContext() {
    var el = $("ask-context");
    if (!el) return;
    var s = window.GaiusSurface || {};
    var clock = s.clock || clockObject();
    var tz = clock.timezone || "";
    if (s.focus && s.focus.title) {
      el.textContent =
        "Looking at " +
        (s.focus.kind || "item") +
        " · " +
        s.focus.title +
        (tz ? " · " + tz : "");
      return;
    }
    var page = s.page || location.pathname;
    el.textContent = "Looking at " + page + (tz ? " · " + tz : "");
  }

  function ymd(d) {
    var y = d.getFullYear();
    var m = String(d.getMonth() + 1).padStart(2, "0");
    var day = String(d.getDate()).padStart(2, "0");
    return y + "-" + m + "-" + day;
  }

  function atHour(d, hour) {
    return new Date(d.getFullYear(), d.getMonth(), d.getDate(), hour, 0, 0).toISOString();
  }

  function tzOffset(d) {
    var off = -d.getTimezoneOffset();
    var sign = off >= 0 ? "+" : "-";
    var abs = Math.abs(off);
    return sign + String(Math.floor(abs / 60)).padStart(2, "0") + ":" + String(abs % 60).padStart(2, "0");
  }

  function clockObject() {
    var now = new Date();
    var tom = new Date(now.getTime());
    tom.setDate(tom.getDate() + 1);
    var tm = atHour(tom, 9);
    var tme = new Date(tm);
    tme.setMinutes(tme.getMinutes() + 30);
    var todayM = atHour(now, 9);
    var todayE = new Date(todayM);
    todayE.setMinutes(todayE.getMinutes() + 30);
    var tz = "";
    try {
      tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
    } catch (e) {}
    var clock = {
      timezone: tz,
      offset: tzOffset(now),
      today: ymd(now),
      tomorrow: ymd(tom),
      now: now.toISOString(),
      today_morning: todayM,
      today_morning_end: todayE.toISOString(),
      tomorrow_morning: tm,
      tomorrow_morning_end: tme.toISOString(),
      session_minutes: 30,
    };
    window.GaiusSurface = window.GaiusSurface || {};
    window.GaiusSurface.clock = clock;
    return clock;
  }

  function clockBlock() {
    var c = clockObject();
    return [
      "## Clock",
      "timezone: " + c.timezone + " (" + c.offset + ")",
      "today: " + c.today,
      "tomorrow: " + c.tomorrow,
      "now: " + c.now,
      "today_morning: " + c.today_morning,
      "today_morning_end: " + c.today_morning_end,
      "tomorrow_morning: " + c.tomorrow_morning,
      "tomorrow_morning_end: " + c.tomorrow_morning_end,
      "session_minutes: 30",
    ].join("\n");
  }

  function looksLikeWrite(text) {
    var t = String(text || "").toLowerCase();
    var verbs = /create|schedule|book|add |put |update|reschedule|rename|make an|make a /;
    var nouns = /event|session|reminder|agenda|meeting|calendar|brief|list|memo|letter|catch-up|catch up/;
    return verbs.test(t) && nouns.test(t);
  }

  function surfaceText() {
    var s = window.GaiusSurface || {};
    var lines = ["## Surface", "page: " + (s.page || location.pathname), clockBlock()];
    if (s.focus) {
      lines.push("## Focus");
      Object.keys(s.focus).forEach(function (k) {
        var v = s.focus[k];
        if (v === undefined || v === null || v === "") return;
        if (k === "path") v = basename(v);
        lines.push(k + ": " + String(v).slice(0, 4000));
      });
    } else {
      lines.push("## Focus", "(none — user has not opened an item)");
    }
    var near = s.nearby || [];
    if (near.length) {
      lines.push("## Nearby");
      near.slice(0, 16).forEach(function (it) {
        var day = it.day || "";
        var when = it.when || "";
        lines.push(
          "- " +
            [it.kind, day, when, it.title].filter(Boolean).join(" · ")
        );
      });
    }
    if (s.ops) {
      lines.push("## Terminal ops");
      lines.push(JSON.stringify(s.ops).slice(0, 6000));
    }
    return lines.join("\n");
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function renderMd(src) {
    if (window.GaiusMd) return window.GaiusMd.renderMd(src);
    var t = escapeHtml(src || "");
    t = t.replace(/`([^`]+)`/g, "<code>$1</code>");
    t = t.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    t = t.replace(/^### (.+)$/gm, "<h4>$1</h4>");
    t = t.replace(/^## (.+)$/gm, "<h3>$1</h3>");
    t = t.replace(/^- (.+)$/gm, "<li>$1</li>");
    t = t.replace(/(<li>.*<\/li>\n?)+/g, "<ul>$&</ul>");
    t = t.replace(/\n{2,}/g, "</p><p>");
    return "<p>" + t + "</p>";
  }

  function addBubble(role, text, reasoning) {
    var log = $("ask-log");
    if (!log) return;
    var art = document.createElement("article");
    art.className = "ask-msg ask-" + role;
    if (role === "assistant" && reasoning) {
      var det = document.createElement("details");
      det.className = "ask-think";
      var sum = document.createElement("summary");
      sum.textContent = "Thinking";
      var pre = document.createElement("pre");
      pre.textContent = reasoning;
      det.append(sum, pre);
      art.appendChild(det);
    }
    var body = document.createElement("div");
    body.className = "ask-md";
    if (role === "user") body.textContent = text;
    else body.innerHTML = renderMd(text);
    art.appendChild(body);
    log.appendChild(art);
    log.scrollTop = log.scrollHeight;
  }

  function startLive() {
    var log = $("ask-log");
    var art = document.createElement("article");
    art.className = "ask-msg ask-assistant ask-live";
    var det = document.createElement("details");
    det.className = "ask-think";
    det.open = true;
    var sum = document.createElement("summary");
    sum.textContent = "Working";
    var status = document.createElement("div");
    status.className = "ask-status";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    var spin = document.createElement("span");
    spin.className = "ask-status-spin";
    spin.setAttribute("aria-hidden", "true");
    var latest = document.createElement("span");
    latest.className = "ask-status-latest";
    latest.textContent = "Consulting Engine…";
    var count = document.createElement("span");
    count.className = "ask-status-count";
    status.append(spin, latest, count);
    var prog = document.createElement("ul");
    prog.className = "ask-progress";
    var pre = document.createElement("pre");
    det.append(sum, status, prog, pre);
    var body = document.createElement("div");
    body.className = "ask-md";
    art.append(det, body);
    if (log) {
      log.appendChild(art);
      log.scrollTop = log.scrollHeight;
    }
    var live = {
      art: art,
      det: det,
      sum: sum,
      latest: latest,
      count: count,
      prog: prog,
      pre: pre,
      body: body,
      hist: ["Consulting Engine…"],
      t0: Date.now(),
      clock: null,
    };
    live.clock = setInterval(function () {
      if (!live.art.classList.contains("ask-live")) return;
      var s = Math.floor((Date.now() - live.t0) / 1000);
      live.sum.textContent = "Working · " + s + "s";
    }, 1000);
    return live;
  }

  function setStatus(live, text) {
    if (!live || !text) return;
    live.latest.textContent = text;
    live.latest.title = text;
    var last = live.hist[live.hist.length - 1];
    if (last !== text) {
      live.hist.push(text);
      if (live.count) {
        live.count.textContent = live.hist.length > 1 ? String(live.hist.length) : "";
      }
    }
    var log = $("ask-log");
    if (log) log.scrollTop = log.scrollHeight;
  }

  function pushProgress(live, text) {
    if (!live || !text) return;
    var last = live.prog.lastElementChild;
    if (last && last.textContent === text) return;
    var li = document.createElement("li");
    li.textContent = text;
    live.prog.appendChild(li);
    live.prog.scrollTop = live.prog.scrollHeight;
    var log = $("ask-log");
    if (log) log.scrollTop = log.scrollHeight;
  }

  function finishLive(live) {
    if (!live) return;
    if (live.clock) {
      clearInterval(live.clock);
      live.clock = null;
    }
    live.art.classList.remove("ask-live");
  }

  function setBusy(on) {
    busy = on;
    var send = $("ask-send");
    var input = $("ask-input");
    if (send) send.disabled = on;
    if (input) input.disabled = on;
  }

  function send(text) {
    text = (text || "").trim();
    if (!text || busy) return;
    addBubble("user", text);
    history.push({ role: "user", content: text });
    $("ask-input").value = "";
    setBusy(true);
    var live = startLive();
    currentLive = live;
    var ctx = $("ask-context");
    setStatus(live, "Consulting Engine…");
    pushProgress(live, (ctx && ctx.textContent) || "Looking at this page");
    var messages = [
      { role: "system", content: SYSTEM + "\n\n" + surfaceText() },
    ].concat(history.slice(-12));
    var answer = "";
    var reasoning = "";
    fetch("/v1/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: "ask",
        messages: messages,
        max_tokens: 4096,
        temperature: 0.2,
        stream: true,
        escalate: looksLikeWrite(text) ? "thinking" : "",
        clock: clockObject(),
      }),
    })
      .then(function (r) {
        if (!r.ok) {
          return r.text().then(function (t) {
            throw new Error(t || "ask " + r.status);
          });
        }
        if (!r.body || !r.body.getReader) {
          return r.text().then(function (t) {
            var data = JSON.parse(t);
            var msg = (((data.choices || [])[0] || {}).message) || {};
            answer = msg.content || "";
            reasoning = msg.reasoning_content || "";
          });
        }
        var reader = r.body.getReader();
        var dec = new TextDecoder();
        var buf = "";
        function step() {
          return reader.read().then(function (res) {
            if (res.done) return;
            buf += dec.decode(res.value, { stream: true });
            var blocks = buf.split("\n\n");
            buf = blocks.pop() || "";
            blocks.forEach(function (block) {
              var line = block
                .split("\n")
                .filter(function (l) {
                  return l.indexOf("data:") === 0;
                })
                .map(function (l) {
                  return l.slice(5).trim();
                })
                .join("");
              if (!line || line === "[DONE]") return;
              var obj;
              try {
                obj = JSON.parse(line);
              } catch (e) {
                return;
              }
              var delta = (((obj.choices || [])[0] || {}).delta) || {};
              if (delta.status) setStatus(live, delta.status);
              if (delta.progress) pushProgress(live, delta.progress);
              if (delta.agenda) applyAgenda(delta.agenda);
              if (typeof delta.reasoning_content === "string") {
                reasoning += delta.reasoning_content;
                live.pre.textContent = reasoning;
              }
              if (typeof delta.content === "string") {
                answer += delta.content;
                live.body.innerHTML = renderMd(answer);
              }
            });
            var log = $("ask-log");
            if (log) log.scrollTop = log.scrollHeight;
            return step();
          });
        }
        return step();
      })
      .then(function () {
        history.push({ role: "assistant", content: answer || "(empty)" });
        if (!answer && !reasoning) {
          live.body.innerHTML = renderMd("(empty)");
        }
        live.sum.textContent = reasoning ? "Thinking" : "Working";
        finishLive(live);
        if (currentLive === live) currentLive = null;
      })
      .catch(function (e) {
        pushProgress(live, String(e.message || e));
        live.body.innerHTML = renderMd(String(e.message || e));
        finishLive(live);
        if (currentLive === live) currentLive = null;
      })
      .then(function () {
        setBusy(false);
        if ($("ask-input")) $("ask-input").focus();
      });
  }

  function reset() {
    history = [];
    artSeen = {};
    if (currentLive) {
      finishLive(currentLive);
      currentLive = null;
    }
    var log = $("ask-log");
    if (log) log.replaceChildren();
    fetch("/api/gaius/v1/ask/artifacts", { method: "DELETE" })
      .then(function (r) {
        return r.ok ? r.json() : null;
      })
      .then(function (d) {
        if (d && typeof d.gen === "number") artGen = d.gen;
      })
      .catch(function () {});
  }

  var artGen = 0;
  var artSeen = {};
  var artPrimed = false;

  function renderTable(rows) {
    var wrap = document.createElement("div");
    wrap.className = "ask-art-table";
    if (!rows.length) {
      wrap.textContent = "(empty table)";
      return wrap;
    }
    var keys = [];
    rows.forEach(function (r) {
      Object.keys(r || {}).forEach(function (k) {
        if (keys.indexOf(k) < 0) keys.push(k);
      });
    });
    var tbl = document.createElement("table");
    var thead = document.createElement("thead");
    var hr = document.createElement("tr");
    keys.forEach(function (k) {
      var th = document.createElement("th");
      th.textContent = k;
      hr.appendChild(th);
    });
    thead.appendChild(hr);
    tbl.appendChild(thead);
    var tb = document.createElement("tbody");
    rows.forEach(function (r) {
      var tr = document.createElement("tr");
      keys.forEach(function (k) {
        var td = document.createElement("td");
        var v = r[k];
        td.textContent = v == null ? "" : String(v);
        tr.appendChild(td);
      });
      tb.appendChild(tr);
    });
    tbl.appendChild(tb);
    wrap.appendChild(tbl);
    return wrap;
  }

  function renderLinks(items) {
    var ul = document.createElement("ul");
    ul.className = "ask-art-links";
    items.forEach(function (it) {
      var href = (it && (it.href || it.url)) || "";
      var title = (it && (it.title || it.href || it.url)) || href;
      var li = document.createElement("li");
      if (href) {
        var a = document.createElement("a");
        a.href = href;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        a.textContent = title;
        li.appendChild(a);
      } else {
        li.textContent = title;
      }
      if (it && it.detail) {
        var d = document.createElement("span");
        d.className = "ask-art-meta";
        d.textContent = " — " + it.detail;
        li.appendChild(d);
      }
      ul.appendChild(li);
    });
    return ul;
  }

  function ohlcSvg(bars) {
    if (window.GaiusMd) return window.GaiusMd.ohlcSvg(bars);
    var w = 300;
    var h = 132;
    var pad = 8;
    var n = bars.length;
    if (!n) return "";
    var lows = bars.map(function (b) { return Number(b.l); });
    var highs = bars.map(function (b) { return Number(b.h); });
    var min = Math.min.apply(null, lows);
    var max = Math.max.apply(null, highs);
    var span = max - min || 1;
    var gap = (w - pad * 2) / n;
    var bw = Math.max(1, Math.min(6, gap * 0.6));
    var parts = [
      '<svg class="ask-ohlc" viewBox="0 0 ' + w + " " + h + '" width="100%" height="' + h + '" role="img">',
    ];
    bars.forEach(function (b, i) {
      var o = Number(b.o);
      var c = Number(b.c);
      var hi = Number(b.h);
      var lo = Number(b.l);
      var x = pad + i * gap + gap / 2;
      var y = function (v) {
        return pad + ((max - v) / span) * (h - pad * 2);
      };
      var up = c >= o;
      var color = up ? "var(--color-kumo-success)" : "var(--color-kumo-danger)";
      var y1 = y(hi);
      var y2 = y(lo);
      var yo = y(o);
      var yc = y(c);
      var top = Math.min(yo, yc);
      var bh = Math.max(1, Math.abs(yc - yo));
      parts.push(
        '<line x1="' + x + '" x2="' + x + '" y1="' + y1 + '" y2="' + y2 + '" stroke="' + color + '" stroke-width="1"/>'
      );
      parts.push(
        '<rect x="' +
          (x - bw / 2) +
          '" y="' +
          top +
          '" width="' +
          bw +
          '" height="' +
          bh +
          '" fill="' +
          color +
          '"/>'
      );
    });
    parts.push("</svg>");
    return parts.join("");
  }

  function applyAgenda(payload) {
    var item = (payload && payload.item) || payload;
    if (!item || typeof item !== "object") return;
    document.dispatchEvent(
      new CustomEvent("gaius-agenda-upsert", { detail: item })
    );
    if (window.GaiusSurface && window.GaiusSurface.setFocus) {
      window.GaiusSurface.setFocus({
        kind: item.kind || "event",
        intent: item.intent || "",
        title: item.title || "item",
        path: item.path || "",
        starts: item.starts || "",
        ends: item.ends || "",
        body: item.body || item.excerpt || "",
      });
    }
  }

  function presentArtifact(item) {
    var id = item.id || "";
    if (id && artSeen[id]) return;
    if (id) artSeen[id] = true;
    if (item.type === "ohlc" || item.type === "table" || item.type === "links") {
      setOpen(true);
    } else if (!isOpen() && !busy) {
      return;
    }
    if (window.GaiusSurface) {
      window.GaiusSurface.setFocus({
        kind: item.type || "artifact",
        title: item.title || item.symbol || "artifact",
        symbol: item.symbol || "",
        body: item.type === "ohlc" ? (item.bars || []).length + " bars" : item.body || "",
      });
    }
    var log = $("ask-log");
    if (!log) return;
    if (item.type === "ohlc" && item.symbol) {
      var dup = log.querySelector('[data-ohlc="' + item.symbol + '"]');
      if (dup) dup.remove();
    }
    var art = document.createElement("article");
    art.className = "ask-msg ask-artifact";
    if (item.type === "ohlc" && item.symbol) {
      art.setAttribute("data-ohlc", item.symbol);
    }
    var head = document.createElement("div");
    head.className = "ask-art-head";
    head.textContent = item.title || item.symbol || item.type || "artifact";
    art.appendChild(head);
    if (item.type === "ohlc") {
      var wrap = document.createElement("div");
      wrap.className = "ask-art-chart";
      wrap.innerHTML = ohlcSvg(item.bars || []);
      art.appendChild(wrap);
      var meta = document.createElement("div");
      meta.className = "ask-art-meta";
      var last = (item.bars || [])[item.bars.length - 1];
      meta.textContent =
        (item.symbol || "") +
        (last ? " · " + last.t + "  c " + last.c : "");
      art.appendChild(meta);
    } else if (item.type === "table") {
      art.appendChild(renderTable(item.rows || []));
    } else if (item.type === "links") {
      art.appendChild(renderLinks(item.links || item.rows || []));
    } else {
      var body = document.createElement("div");
      body.className = "ask-md";
      body.innerHTML = renderMd(item.body || item.title || "");
      art.appendChild(body);
    }
    log.appendChild(art);
    log.scrollTop = log.scrollHeight;
  }

  function pollArtifacts() {
    fetch("/api/gaius/v1/ask/artifacts?since=" + artGen)
      .then(function (r) {
        return r.ok ? r.json() : null;
      })
      .then(function (d) {
        if (!d) return;
        var next = typeof d.gen === "number" ? d.gen : artGen;
        if (!artPrimed) {
          artGen = next;
          artPrimed = true;
          return;
        }
        artGen = next;
        (d.items || []).forEach(presentArtifact);
      })
      .catch(function () {});
  }

  function boot() {
    if (!$("ask-panel")) return;
    var toggle = $("ask-toggle");
    if (toggle) {
      toggle.addEventListener("click", function () {
        setOpen(!isOpen());
      });
    }
    $("ask-close").addEventListener("click", function () {
      setOpen(false);
    });
    $("ask-new").addEventListener("click", reset);
    $("ask-form").addEventListener("submit", function (ev) {
      ev.preventDefault();
      send($("ask-input").value);
    });
    $("ask-input").addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" && !ev.shiftKey) {
        ev.preventDefault();
        send($("ask-input").value);
      }
    });
    document.addEventListener("keydown", function (ev) {
      if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "e") {
        ev.preventDefault();
        setOpen(!isOpen());
      }
    });
    document.addEventListener("gaius-surface", paintContext);
    try {
      localStorage.removeItem("gaius-ask-open");
    } catch (e) {}
    setOpen(false);
    paintContext();
    pollArtifacts();
    setInterval(pollArtifacts, 1000);
    pollOps();
    setInterval(pollOps, 2000);
  }

  function pollOps() {
    fetch("/api/gaius/v1/ops")
      .then(function (r) {
        return r.ok ? r.json() : null;
      })
      .then(function (d) {
        if (!d || !window.GaiusSurface) return;
        window.GaiusSurface.ops = d;
        var ctx = $("ask-context");
        if (!ctx) return;
        if (d.thinking_busy) {
          var el = d.complete && d.complete[0];
          var extra = el
            ? " · Terminal thinking " + (el.elapsed_s || 0) + "s"
            : " · Terminal thinking";
          if (ctx.textContent.indexOf("Terminal thinking") < 0) {
            ctx.textContent = (ctx.textContent || "") + extra;
          }
        }
      })
      .catch(function () {});
  }

  window.GaiusSurface.setFocus = function (focus) {
    window.GaiusSurface.focus = focus || null;
    document.dispatchEvent(new Event("gaius-surface"));
  };
  window.GaiusSurface.setNearby = function (nearby) {
    window.GaiusSurface.nearby = nearby || [];
    document.dispatchEvent(new Event("gaius-surface"));
  };
  window.GaiusSurface.setPage = function (page) {
    window.GaiusSurface.page = page || location.pathname;
    document.dispatchEvent(new Event("gaius-surface"));
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
