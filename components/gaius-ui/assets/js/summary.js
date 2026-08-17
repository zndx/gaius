(function () {
  var CLOSE_SVG =
    '<svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true">' +
    '<path fill="currentColor" d="M6.4 5l5.6 5.6L17.6 5 19 6.4 13.4 12l5.6 5.6-1.4 1.4-5.6-5.6L6.4 19 5 17.6 10.6 12 5 6.4 6.4 5z"/>' +
    "</svg>";

  var state = {
    section: "",
    lens: "",
    week: "",
    root: "current",
    landingId: "",
    trail: [],
    cache: {},
    schedules: [],
    cadence: "",
    gen: 0,
  };

  function $(id) {
    return document.getElementById(id);
  }

  function qs() {
    var q = new URLSearchParams(location.search);
    var root = q.get("root") || "current";
    if (root !== "archive" && root !== "current" && root !== "scratch") root = "current";
    return {
      section: q.get("section") || "",
      lens: q.get("lens") || "",
      week: q.get("week") || "",
      cadence: q.get("cadence") || "",
      open: q.get("open") || "",
      root: root,
    };
  }

  function writeUrl() {
    var q = new URLSearchParams();
    if (state.section) q.set("section", state.section);
    if (state.lens) q.set("lens", state.lens);
    if (state.cadence) q.set("cadence", state.cadence);
    if (state.week) q.set("week", state.week);
    if (state.root && state.root !== "current") q.set("root", state.root);
    if (state.trail.length) {
      var last = state.trail[state.trail.length - 1];
      if (!state.cadence || last !== "schedule/" + state.cadence) q.set("open", last);
    }
    var s = q.toString();
    history.replaceState(null, "", s ? location.pathname + "?" + s : location.pathname);
  }

  function markTabs() {
    document.querySelectorAll(".sum-tab[data-section]").forEach(function (b) {
      b.classList.toggle("active", b.getAttribute("data-section") === state.section);
    });
    document.querySelectorAll(".sum-tab[data-lens]").forEach(function (b) {
      b.classList.toggle("active", b.getAttribute("data-lens") === state.lens);
    });
    var weekBtn = $("sum-week");
    if (weekBtn) {
      weekBtn.classList.toggle("active", !state.lens && trailIsLanding());
    }
    var root = $("sum-root");
    if (root && root.value !== state.root) root.value = state.root;
    document.querySelectorAll(".sum-tab[data-cadence]").forEach(function (b) {
      b.classList.toggle("active", b.getAttribute("data-cadence") === state.cadence);
    });
  }

  function trailIsLanding() {
    return state.trail.length > 0 && state.landingId && state.trail[0] === state.landingId;
  }

  function panelHtml(note, i) {
    var body = "";
    if (window.GaiusMd && note.body) body = window.GaiusMd.renderMd(note.body);
    var meta = [note.section, note.lens, note.week].filter(Boolean).join(" · ");
    var fork = "";
    if (note.lens === "schedule" && note.origin_id) {
      fork =
        '<button type="button" class="btn sum-trig" data-sched="' +
        escapeHtml(note.origin_id) +
        '">Trigger</button>';
    } else if (!note.virtual) {
      fork =
        '<button type="button" class="btn sum-fork" data-i="' +
        i +
        '">Fork</button>';
    }
    var closeTitle =
      i === 0 ? "Close panels to the right" : "Close this panel and those to the right";
    return (
      '<article class="sum-panel" data-i="' +
      i +
      '">' +
      '<header class="sum-panel-head">' +
      "<h2>" +
      escapeHtml(note.title || note.id) +
      "</h2>" +
      '<span class="muted mono sum-panel-meta">' +
      escapeHtml(meta) +
      "</span>" +
      fork +
      '<button type="button" class="sum-close" data-i="' +
      i +
      '" title="' +
      closeTitle +
      '" aria-label="' +
      closeTitle +
      '">' +
      CLOSE_SVG +
      "</button>" +
      "</header>" +
      '<div class="sum-panel-body agenda-md">' +
      body +
      "</div>" +
      '<footer class="muted mono sum-panel-id">' +
      escapeHtml(note.id) +
      "</footer></article>"
    );
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function closeFrom(i) {
    // Leftmost stays; close at i drops that panel and everything to its right.
    // Close on the seed (i === 0) only clears the right-ward trail.
    if (i <= 0) {
      state.trail = state.trail.slice(0, 1);
    } else {
      state.trail = state.trail.slice(0, i);
    }
    paint();
    writeUrl();
  }

  function paint() {
    var el = $("sum-trail");
    el.innerHTML = state.trail
      .map(function (id, i) {
        var note = state.cache[id];
        if (!note) return '<article class="sum-panel"><p class="muted">loading…</p></article>';
        return panelHtml(note, i);
      })
      .join("");
    el.querySelectorAll(".agenda-wiki").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var panel = btn.closest(".sum-panel");
        var i = panel ? parseInt(panel.getAttribute("data-i"), 10) : state.trail.length - 1;
        hopFrom(i, btn.getAttribute("data-wiki"));
      });
    });
    el.querySelectorAll(".sum-close").forEach(function (btn) {
      btn.addEventListener("click", function () {
        closeFrom(parseInt(btn.getAttribute("data-i"), 10));
      });
    });
    el.querySelectorAll(".sum-fork").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var i = parseInt(btn.getAttribute("data-i"), 10);
        fork(state.trail[i]);
      });
    });
    el.querySelectorAll(".sum-trig").forEach(function (btn) {
      btn.addEventListener("click", function () {
        triggerSchedule(btn.getAttribute("data-sched"));
      });
    });
    markTabs();
  }

  function cacheNote(n) {
    if (!n || !n.id) return;
    state.cache[n.id] = n;
  }

  function rootNote() {
    if (state.root === "current") return;
    $("sum-foot").textContent =
      state.root + " is not projected yet — showing Current. · federation.project=gaius";
  }

  async function loadIndex(opts) {
    opts = opts || {};
    var gen = ++state.gen;
    var url =
      "/api/gaius/v1/summary?section=" +
      encodeURIComponent(state.section) +
      "&lens=" +
      encodeURIComponent(state.lens) +
      "&week=" +
      encodeURIComponent(state.week);
    var r = await fetch(url);
    var data = await r.json();
    if (!r.ok || data.error) {
      if (gen !== state.gen) return;
      $("sum-week").textContent = "unreachable";
      $("sum-trail").innerHTML =
        '<div class="cog-error">' + escapeHtml(data.error || r.statusText) + "</div>";
      return;
    }
    if (gen !== state.gen) return;
    state.week = data.week || state.week;
    state.landingId = data.landing_id || "";
    $("sum-week").textContent = data.week || "—";
    if (state.cadence) {
      return;
    }
    $("sum-foot").textContent =
      (data.items || []).length +
      " trailheads · landing " +
      (data.landing_id || "—") +
      " · federation.project=gaius";
    rootNote();
    if (data.seed) cacheNote(data.seed);
    (data.items || []).forEach(cacheNote);
    if (state.landingId && !state.cache[state.landingId]) {
      await getNote(state.landingId);
      if (gen !== state.gen) return;
    }
    var seedId = (state.lens || state.section)
      ? data.seed && data.seed.id
      : state.landingId || (data.seed && data.seed.id);
    var open = opts.keepOpen ? qs().open : "";
    if (open && open.indexOf("schedule/") === 0) open = "";
    if (opts.keepOpen && open && open !== seedId) {
      if (!state.cache[open]) await getNote(open);
      if (gen !== state.gen) return;
      if (state.cache[open]) {
        state.trail = seedId ? [seedId, open] : [open];
      } else if (seedId) {
        state.trail = [seedId];
      }
    } else if (seedId) {
      state.trail = [seedId];
    } else {
      state.trail = [];
    }
    paint();
    writeUrl();
  }

  async function getNote(id) {
    var r = await fetch(
      "/api/gaius/v1/summary/note?id=" +
        encodeURIComponent(id) +
        "&section=" +
        encodeURIComponent(state.section) +
        "&lens=" +
        encodeURIComponent(state.lens) +
        "&week=" +
        encodeURIComponent(state.week)
    );
    var data = await r.json();
    if (r.ok && !data.error) cacheNote(data);
    return data;
  }

  async function hopFrom(i, target) {
    var t = (target || "").replace(/^\/+/, "");
    if (t.indexOf("schedule/") === 0) {
      var job = t.slice("schedule/".length);
      var card = state.schedules.find(function (c) {
        return c.id === job || c.task_type === job;
      });
      if (card) {
        var note = scheduleNote(card);
        cacheNote(note);
        state.trail = state.trail.slice(0, i + 1);
        state.trail.push(note.id);
        paint();
        writeUrl();
        return;
      }
    }
    var from = state.trail[i] || "";
    var r = await fetch("/api/gaius/v1/summary/hop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        from_id: from,
        target: target,
        section: state.section,
        lens: state.lens,
        week: state.week,
      }),
    });
    var data = await r.json();
    if (!r.ok || data.error) {
      $("sum-foot").textContent = data.error || "hop failed";
      return;
    }
    cacheNote(data);
    var id = data.id || data.resolved_id;
    if (id) {
      state.trail = state.trail.slice(0, i + 1);
      state.trail.push(id);
      paint();
      writeUrl();
    }
  }

  async function fork(id) {
    var r = await fetch("/api/gaius/v1/summary/fork", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: id }),
    });
    var data = await r.json();
    if (!r.ok || data.error) {
      $("sum-foot").textContent = data.error || "fork failed";
      return;
    }
    cacheNote(data);
    if (data.id) {
      state.trail.push(data.id);
      paint();
      writeUrl();
    }
  }

  function landOnWeek() {
    state.section = "";
    state.lens = "";
    state.cadence = "";
    markTabs();
    loadIndex();
  }

  function scheduleNote(card) {
    var id = "schedule/" + card.id;
    var body = [
      "# " + card.id,
      "",
      "- cron: `" + card.cron + "`",
      "- task: `" + card.task_type + "`",
      "- source: **" + card.source + "** (Airflow schedules Metaflow when available; pg_cron otherwise)",
      "- enabled: " + (card.enabled ? "yes" : "no"),
      "",
      "Trigger enqueues `scheduled_tasks` for the engine processor.",
      "",
    ].join("\n");
    return {
      id: id,
      title: card.id,
      body: body,
      section: "schedule",
      lens: "schedule",
      week: state.week,
      links: [],
      origin_id: card.id,
      excerpt: card.cron + " · " + card.task_type,
      virtual: true,
    };
  }

  function cadenceOf(card) {
    if (card.cadence) return card.cadence;
    var parts = String(card.cron || "").split(/\s+/);
    if (parts.length < 5) return "extended";
    var hour = parts[1];
    var dom = parts[2];
    var month = parts[3];
    var dow = parts[4];
    if (month !== "*") return "extended";
    if (dom !== "*") return "extended";
    if (dow.indexOf(",") >= 0) return "extended";
    if (dow !== "*") return "weekly";
    if (hour === "*" || hour.indexOf("*/") === 0) return "hourly";
    if (hour.split(",").length >= 3) return "hourly";
    return "daily";
  }

  function cadenceNote(cadence) {
    var label = cadence.charAt(0).toUpperCase() + cadence.slice(1);
    var cards = state.schedules.filter(function (c) {
      return cadenceOf(c) === cadence;
    });
    var lines = [
      "# " + label + " clocks",
      "",
      cards.length
        ? cards.length + " enqueue clock(s). Hop a name, then Trigger."
        : "None in this cadence.",
      "",
    ];
    cards.forEach(function (c) {
      cacheNote(scheduleNote(c));
      lines.push(
        "- [[schedule/" + c.id + "|" + c.id + "]] `" + c.cron + "` → `" + c.task_type + "`"
      );
    });
    lines.push("");
    var id = "schedule/" + cadence;
    return {
      id: id,
      title: label + " clocks",
      body: lines.join("\n"),
      section: "schedule",
      lens: "schedule",
      week: state.week,
      links: cards.map(function (c) { return "schedule/" + c.id; }),
      excerpt: cards.length + " clocks",
      virtual: true,
    };
  }

  async function openCadence(cadence) {
    state.gen += 1;
    state.cadence = cadence;
    state.section = "";
    state.lens = "";
    if (!state.schedules.length) await loadSchedules();
    var note = cadenceNote(cadence);
    cacheNote(note);
    state.trail = [note.id];
    paint();
    writeUrl();
  }

  async function loadSchedules() {
    try {
      var r = await fetch("/api/gaius/v1/summary/schedules");
      var data = await r.json();
      if (!r.ok || data.error) {
        $("sum-foot").textContent = data.error || "schedule catalog unreachable";
        return;
      }
      state.schedules = data.items || [];
    } catch (e) {
      $("sum-foot").textContent = "schedule catalog unreachable";
    }
  }

  async function triggerSchedule(jobId) {
    var r = await fetch("/api/gaius/v1/summary/trigger", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: jobId }),
    });
    var data = await r.json();
    if (!r.ok || data.error) {
      $("sum-foot").textContent = data.error || "trigger failed";
      return;
    }
    $("sum-foot").textContent =
      "enqueued " + data.task_type + " #" + data.task_id + " · federation.project=gaius";
  }

  document.querySelectorAll(".sum-tab[data-section]").forEach(function (b) {
    b.addEventListener("click", function () {
      var next = b.getAttribute("data-section") || "";
      state.section = state.section === next ? "" : next;
      state.lens = "";
      state.cadence = "";
      markTabs();
      loadIndex();
    });
  });
  document.querySelectorAll(".sum-tab[data-lens]").forEach(function (b) {
    b.addEventListener("click", function () {
      var next = b.getAttribute("data-lens") || "";
      state.lens = state.lens === next ? "" : next;
      state.section = "";
      state.cadence = "";
      markTabs();
      loadIndex();
    });
  });
  document.querySelectorAll(".sum-tab[data-cadence]").forEach(function (b) {
    b.addEventListener("click", function () {
      openCadence(b.getAttribute("data-cadence") || "daily");
    });
  });
  $("sum-week").addEventListener("click", landOnWeek);
  $("sum-root").addEventListener("change", function () {
    var next = $("sum-root").value || "current";
    state.root = next;
    writeUrl();
    if (next !== "current") {
      rootNote();
      return;
    }
    $("sum-foot").textContent = "Current · federation.project=gaius";
  });

  var init = qs();
  state.section = init.cadence ? "" : init.section;
  state.lens = init.cadence || init.section ? "" : init.lens;
  state.week = init.week;
  state.root = init.root;
  markTabs();
  if (init.cadence) {
    openCadence(init.cadence).then(function () {
      var job = init.open || "";
      if (job.indexOf("schedule/") === 0 && job !== "schedule/" + init.cadence) {
        hopFrom(0, job);
      }
    });
  } else {
    loadIndex({ keepOpen: true });
    loadSchedules();
  }
})();
