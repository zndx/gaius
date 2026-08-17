(function () {
  var el = document.getElementById("terminal");
  var statusEl = document.getElementById("term-status");
  if (!el) return;

  function setStatus(s, color) {
    if (!statusEl) return;
    statusEl.textContent = s;
    statusEl.style.color = color || "#d99d54";
  }

  function banner(msg) {
    el.style.color = "#c9d1d9";
    el.style.fontFamily = "ui-monospace, monospace";
    el.style.padding = "16px";
    el.style.whiteSpace = "pre-wrap";
    el.textContent = msg;
  }

  function sessionId() {
    var k = "gaius-terminal-session";
    var s = localStorage.getItem(k);
    if (s) return s;
    s = crypto.randomUUID ? crypto.randomUUID() : String(Date.now());
    localStorage.setItem(k, s);
    return s;
  }

  function loadGhostty() {
    if (window.__ghostty || window.__ghosttyLoading) return;
    window.__ghosttyLoading = true;
    var s = document.createElement("script");
    s.type = "module";
    s.textContent = [
      "import { Ghostty, Terminal, FitAddon } from '/assets/ghostty/ghostty-web.js';",
      "try {",
      "  const instance = await Ghostty.load('/assets/ghostty/ghostty-vt.wasm');",
      "  window.__ghostty = { Ghostty, Terminal, FitAddon, instance };",
      "} catch (e) { window.__ghosttyError = e; }",
      "window.dispatchEvent(new CustomEvent('ghostty-ready'));",
    ].join("\n");
    document.head.appendChild(s);
  }

  function start() {
    var g = window.__ghostty;
    if (!g) {
      banner(
        window.__ghosttyError
          ? "ghostty-web failed: " + window.__ghosttyError
          : "ghostty-web timed out. Copy atelier/ui/public/ghostty into components/gaius-ui/assets/ghostty/."
      );
      return;
    }

    var term = new g.Terminal({
      ghostty: g.instance,
      cursorBlink: true,
      fontFamily: 'Menlo, Monaco, "Courier New", ui-monospace, monospace',
      fontSize: 13,
      scrollback: 8000,
      theme: {
        background: "#0d1117",
        foreground: "#c9d1d9",
        cursor: "#58a6ff",
        selectionBackground: "rgba(56,139,253,0.4)",
      },
    });
    var fit = new g.FitAddon();
    term.loadAddon(fit);
    term.open(el);
    if (typeof el.focus === "function") el.focus({ preventScroll: true });

    var wrap = document.getElementById("terminal-wrap") || el;
    var sid = sessionId();
    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    var delay = 1000;
    var ws;
    var disposed = false;

    function lockScroll() {
      if (wrap) {
        wrap.scrollTop = 0;
        wrap.scrollLeft = 0;
      }
      el.scrollTop = 0;
      el.scrollLeft = 0;
    }

    function sendResize() {
      if (!ws || ws.readyState !== 1) return;
      ws.send(
        JSON.stringify({
          type: "resize",
          cols: term.cols,
          rows: term.rows,
        })
      );
    }

    function applyFit() {
      fit.fit();
      lockScroll();
      sendResize();
    }

    function connect() {
      if (disposed) return;
      setStatus("connecting…", "#d99d54");
      ws = new WebSocket(proto + "//" + location.host + "/ws/terminal/" + sid);
      ws.onopen = function () {
        delay = 1000;
        setStatus("connected · grok · engine", "#4ec491");
        sendResize();
      };
      ws.onmessage = function (ev) {
        try {
          var msg = JSON.parse(ev.data);
          if (msg.type === "status") {
            setStatus(msg.data || "grok", "#d99d54");
            return;
          }
          if (msg.type === "text") {
            term.write(msg.data);
            lockScroll();
          }
        } catch (e) {
          term.write(ev.data);
        }
      };
      ws.onclose = function () {
        if (disposed) return;
        setStatus("disconnected", "#f28881");
        setTimeout(function () {
          delay = Math.min(delay * 2, 15000);
          connect();
        }, delay);
      };
    }

    term.onData(function (data) {
      if (ws && ws.readyState === 1) {
        ws.send(JSON.stringify({ type: "input", data: data }));
      }
    });

    ["scroll", "focusin"].forEach(function (ev) {
      el.addEventListener(ev, lockScroll, true);
      if (wrap && wrap !== el) wrap.addEventListener(ev, lockScroll, true);
    });

    var ro = new ResizeObserver(function () {
      applyFit();
    });
    ro.observe(wrap);
    requestAnimationFrame(function () {
      applyFit();
      requestAnimationFrame(applyFit);
    });
    connect();
  }

  loadGhostty();
  if (window.__ghostty) start();
  else {
    window.addEventListener("ghostty-ready", start, { once: true });
    setTimeout(function () {
      if (!window.__ghostty && !el.querySelector("canvas") && !el.querySelector("canvas, .xterm")) {
        start();
      }
    }, 15000);
  }
})();
