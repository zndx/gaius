(function () {
  var state = {
    items: [],
    kind: "",
    month: new Date(),
    day: "",
    q: "",
    tag: "",
    windowDays: 14,
    futureLimit: 0,
    pastLimit: 0,
    stickToday: true,
    loadingMore: false,
  };
  var editing = null;
  var sheetMode = "view";
  var lazyObs = null;

  function $(id) {
    return document.getElementById(id);
  }

  function showError(msg) {
    var el = $("agenda-error");
    if (!el) return;
    el.hidden = !msg;
    el.textContent = msg || "";
  }

  function pad(n) {
    return String(n).padStart(2, "0");
  }

  function ymdLocal(d) {
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  }

  function todayKey() {
    return ymdLocal(new Date());
  }

  function itemDay(it) {
    if (it.starts) {
      var d = new Date(it.starts);
      if (!isNaN(d.getTime())) return ymdLocal(d);
    }
    if (it.created_ms) return ymdLocal(new Date(it.created_ms));
    return "";
  }

  function itemSortKey(it) {
    if (it.starts) return String(it.starts);
    if (it.created_ms) return new Date(it.created_ms).toISOString();
    return "";
  }

  function basename(p) {
    return String(p || "").split("/").pop() || "";
  }

  function visibleItems() {
    var q = state.q.trim().toLowerCase();
    return state.items.filter(function (it) {
      if (state.day && itemDay(it) !== state.day) return false;
      if (state.tag && (it.tags || []).indexOf(state.tag) < 0) return false;
      if (!q) return true;
      var hay = ((it.title || "") + " " + (it.excerpt || "") + " " + (it.body || "")).toLowerCase();
      return hay.indexOf(q) >= 0;
    });
  }

  function estimateVisible() {
    var scroller = document.querySelector(".agenda-main");
    var h = (scroller && scroller.clientHeight) || 640;
    return Math.max(6, Math.ceil(h / 80));
  }

  function renderBudget() {
    return Math.max(12, estimateVisible() * 3);
  }

  function browserTz() {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || "";
    } catch (e) {
      return "";
    }
  }

  function load() {
    var url =
      "/api/gaius/v1/agenda?window_days=" +
      encodeURIComponent(state.windowDays) +
      "&kind=" +
      encodeURIComponent(state.kind) +
      "&origin=" +
      encodeURIComponent(todayKey()) +
      "&timezone=" +
      encodeURIComponent(browserTz());
    return fetch(url)
      .then(function (r) {
        return r.text().then(function (t) {
          if (!r.ok) throw new Error(t || "agenda " + r.status);
          return JSON.parse(t);
        });
      })
      .then(function (data) {
        showError("");
        state.items = data.items || [];
        paint();
      })
      .catch(function (e) {
        showError(String(e.message || e));
      });
  }

  function paintCal() {
    var host = $("agenda-cal");
    if (!host) return;
    host.replaceChildren();
    var y = state.month.getFullYear();
    var m = state.month.getMonth();
    var head = document.createElement("div");
    head.className = "agenda-cal-head";
    var prev = document.createElement("button");
    prev.type = "button";
    prev.className = "btn";
    prev.textContent = "‹";
    prev.onclick = function () {
      state.month = new Date(y, m - 1, 1);
      paintCal();
    };
    var next = document.createElement("button");
    next.type = "button";
    next.className = "btn";
    next.textContent = "›";
    next.onclick = function () {
      state.month = new Date(y, m + 1, 1);
      paintCal();
    };
    var title = document.createElement("span");
    title.textContent = state.month.toLocaleString("en", {
      month: "short",
      year: "numeric",
    });
    head.append(prev, title, next);
    host.appendChild(head);
    var grid = document.createElement("div");
    grid.className = "agenda-cal-grid";
    ["S", "M", "T", "W", "T", "F", "S"].forEach(function (d) {
      var s = document.createElement("span");
      s.className = "muted";
      s.textContent = d;
      grid.appendChild(s);
    });
    var first = new Date(y, m, 1);
    var start = first.getDay();
    var days = new Date(y, m + 1, 0).getDate();
    var marked = {};
    state.items.forEach(function (it) {
      var key = itemDay(it);
      if (key) marked[key] = true;
    });
    var today = todayKey();
    for (var i = 0; i < start; i++) grid.appendChild(document.createElement("span"));
    for (var day = 1; day <= days; day++) {
      var key = y + "-" + pad(m + 1) + "-" + pad(day);
      var b = document.createElement("button");
      b.type = "button";
      b.textContent = String(day);
      var cls = "agenda-cal-day";
      if (marked[key]) cls += " has";
      if (key === today) cls += " today";
      if (key === state.day) cls += " selected";
      b.className = cls;
      b.setAttribute("aria-label", key);
      b.onclick = function (k) {
        return function () {
          state.day = state.day === k ? "" : k;
          paint();
        };
      }(key);
      grid.appendChild(b);
    }
    host.appendChild(grid);
  }

  function paintTags() {
    var host = $("agenda-tags");
    if (!host) return;
    var counts = {};
    state.items.forEach(function (it) {
      (it.tags || []).forEach(function (tg) {
        counts[tg] = (counts[tg] || 0) + 1;
      });
    });
    var names = Object.keys(counts).sort();
    host.hidden = !names.length;
    host.replaceChildren();
    names.forEach(function (tg) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "agenda-tag-chip" + (state.tag === tg ? " active" : "");
      b.textContent = tg;
      b.onclick = function () {
        state.tag = state.tag === tg ? "" : tg;
        paint();
      };
      host.appendChild(b);
    });
  }

  function emptyEl(text) {
    var d = document.createElement("div");
    d.className = "agenda-empty";
    d.textContent = text;
    return d;
  }

  function weekday(iso) {
    var p = String(iso || "").split("-");
    if (p.length < 3) return "";
    var d = new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2]));
    return d.toLocaleString("en", { weekday: "short" }).toUpperCase();
  }

  function hmLocal(iso) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    return pad(d.getHours()) + ":" + pad(d.getMinutes());
  }

  function fmtWhen(it) {
    if (it.starts) {
      var st = hmLocal(it.starts);
      var en = it.ends ? hmLocal(it.ends) : "";
      if (st && en) return st + "–" + en;
      if (st) return st;
    }
    if (it.created_ms) {
      var d = new Date(it.created_ms);
      return pad(d.getHours()) + ":" + pad(d.getMinutes());
    }
    return "—";
  }

  function rowEl(it) {
    var row = document.createElement("article");
    row.className =
      "agenda-sched-row kind-" +
      (it.kind || "note") +
      " intent-" +
      (it.intent || "brief") +
      (it.pin ? " pinned" : "");
    row.tabIndex = 0;
    var time = document.createElement("span");
    time.className = "agenda-sched-time mono";
    time.textContent = fmtWhen(it);
    var body = document.createElement("div");
    body.className = "agenda-sched-body";
    var line = document.createElement("div");
    line.className = "agenda-sched-line";
    var chip = document.createElement("span");
    chip.className = "agenda-chip";
    chip.textContent = it.kind;
    var intent = document.createElement("span");
    intent.className = "agenda-chip intent-" + (it.intent || "brief");
    intent.textContent = it.intent || "brief";
    var title = document.createElement("span");
    title.className = "agenda-sched-title";
    title.textContent = it.title || "(untitled)";
    line.append(chip, intent, title);
    if (it.intent === "session") {
      var whom = document.createElement("span");
      whom.className = "agenda-chip";
      whom.textContent = "with " + (it.with || "agents");
      line.appendChild(whom);
    }
    if (it.pin) {
      var pin = document.createElement("span");
      pin.className = "agenda-chip";
      pin.textContent = "pin";
      line.appendChild(pin);
    }
    body.appendChild(line);
    if (it.kind === "list" && it.checks && it.checks.length) {
      var ul = document.createElement("ul");
      ul.className = "agenda-checks";
      it.checks.slice(0, 6).forEach(function (c, idx) {
        var li = document.createElement("li");
        var cb = document.createElement("input");
        cb.type = "checkbox";
        cb.checked = !!c.done;
        cb.addEventListener("click", function (ev) {
          ev.stopPropagation();
          toggleCheck(it, idx, cb.checked);
        });
        var lab = document.createElement("span");
        lab.textContent = c.text || "";
        if (c.done) lab.className = "done";
        li.append(cb, lab);
        ul.appendChild(li);
      });
      body.appendChild(ul);
    } else if (it.excerpt && it.kind !== "event") {
      var p = document.createElement("p");
      p.className = "agenda-sched-excerpt";
      p.textContent = it.excerpt;
      body.appendChild(p);
    }
    if (it.intent === "session" && it.calendar_url) {
      var cal = document.createElement("a");
      cal.className = "agenda-cal-link";
      cal.href = it.calendar_url;
      cal.target = "_blank";
      cal.rel = "noopener";
      cal.textContent = "Add to Google Calendar";
      cal.addEventListener("click", function (ev) {
        ev.stopPropagation();
      });
      body.appendChild(cal);
    }
    if (it.tags && it.tags.length) {
      var tags = document.createElement("div");
      tags.className = "agenda-tags";
      it.tags.forEach(function (tg) {
        var s = document.createElement("span");
        s.textContent = tg;
        tags.appendChild(s);
      });
      body.appendChild(tags);
    }
    row.append(time, body);
    row.addEventListener("click", function () {
      openEditor(it);
    });
    row.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter") openEditor(it);
    });
    return row;
  }

  function splitTimeline(items) {
    var today = todayKey();
    var future = [];
    var now = [];
    var past = [];
    items.forEach(function (it) {
      var d = itemDay(it);
      if (!d || d === today) now.push(it);
      else if (d > today) future.push(it);
      else past.push(it);
    });
    return { future: future, today: now, past: past };
  }

  function ensureLimits(parts) {
    var vis = estimateVisible();
    var bud = renderBudget();
    if (!state.futureLimit) {
      state.futureLimit = Math.min(parts.future.length, vis);
    }
    if (!state.pastLimit) {
      var used = parts.today.length + state.futureLimit;
      state.pastLimit = Math.min(
        parts.past.length,
        Math.max(vis, bud - used)
      );
    }
  }

  function appendDay(host, day, rows, today) {
    var h = document.createElement("h2");
    h.className = "agenda-dayhead" + (day === today ? " today" : "");
    if (day === today) h.id = "agenda-today";
    var num = document.createElement("span");
    num.className = "agenda-daynum";
    num.textContent =
      day === "undated" ? "—" : day.slice(8, 10).replace(/^0/, "") || day;
    var lab = document.createElement("span");
    lab.textContent =
      day === "undated" ? "Undated" : weekday(day) + " · " + day;
    h.append(num, lab);
    host.appendChild(h);
    rows
      .sort(function (a, b) {
        if (a.pin !== b.pin) return a.pin ? -1 : 1;
        return itemSortKey(a).localeCompare(itemSortKey(b));
      })
      .forEach(function (it) {
        host.appendChild(rowEl(it));
      });
  }

  function groupDays(items) {
    var buckets = {};
    items.forEach(function (it) {
      var key = itemDay(it) || "undated";
      if (!buckets[key]) buckets[key] = [];
      buckets[key].push(it);
    });
    return Object.keys(buckets)
      .sort()
      .reverse()
      .map(function (day) {
        return { day: day, rows: buckets[day] };
      });
  }

  function lazyMark(id, label, remaining) {
    var el = document.createElement("div");
    el.id = id;
    el.className = "agenda-lazy";
    el.textContent = remaining
      ? label + " · " + remaining + " more"
      : label;
    return el;
  }

  function pinToday() {
    if (!state.stickToday || state.day) return;
    var scroller = document.querySelector(".agenda-main");
    var todayEl = $("agenda-today");
    if (!scroller || !todayEl) return;
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        var top =
          todayEl.getBoundingClientRect().top -
          scroller.getBoundingClientRect().top +
          scroller.scrollTop;
        scroller.scrollTop = Math.max(0, top - 8);
      });
    });
  }

  function bindLazy() {
    if (lazyObs) {
      lazyObs.disconnect();
      lazyObs = null;
    }
    var scroller = document.querySelector(".agenda-main");
    if (!scroller || typeof IntersectionObserver === "undefined") return;
    lazyObs = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (en) {
          if (!en.isIntersecting) return;
          if (en.target.id === "agenda-more-future") expandFuture();
          if (en.target.id === "agenda-more-past") expandPast();
        });
      },
      { root: scroller, rootMargin: "80px", threshold: 0 }
    );
    var top = $("agenda-more-future");
    var bot = $("agenda-more-past");
    if (top) lazyObs.observe(top);
    if (bot) lazyObs.observe(bot);
  }

  function expandFuture() {
    var parts = splitTimeline(visibleItems());
    if (state.futureLimit < parts.future.length) {
      var scroller = document.querySelector(".agenda-main");
      var oldH = scroller ? scroller.scrollHeight : 0;
      var oldT = scroller ? scroller.scrollTop : 0;
      state.stickToday = false;
      state.futureLimit += estimateVisible();
      paint();
      if (scroller) {
        scroller.scrollTop = oldT + (scroller.scrollHeight - oldH);
      }
      return;
    }
    if (state.loadingMore) return;
    var scroller = document.querySelector(".agenda-main");
    state.loadingMore = true;
    state.windowDays = Math.min(3660, state.windowDays + 30);
    state.futureLimit += estimateVisible();
    state.stickToday = false;
    if (scroller) {
      state.anchor = { h: scroller.scrollHeight, t: scroller.scrollTop };
    }
    load().finally(function () {
      state.loadingMore = false;
    });
  }

  function expandPast() {
    var parts = splitTimeline(visibleItems());
    if (state.pastLimit < parts.past.length) {
      state.stickToday = false;
      state.pastLimit += estimateVisible();
      paint();
      return;
    }
    if (state.loadingMore) return;
    state.loadingMore = true;
    state.windowDays = Math.min(3660, state.windowDays + 30);
    state.pastLimit += estimateVisible();
    state.stickToday = false;
    load().finally(function () {
      state.loadingMore = false;
    });
  }

  function paintSchedule() {
    var host = $("agenda-schedule");
    host.replaceChildren();
    var items = visibleItems();
    var today = todayKey();
    var filtered = !!(state.day || state.q || state.tag);
    if (!items.length && filtered) {
      host.appendChild(emptyEl("Nothing matches this filter."));
      return;
    }
    var parts = splitTimeline(items);
    if (!filtered) ensureLimits(parts);
    var futureItems = filtered
      ? parts.future
      : parts.future.slice(Math.max(0, parts.future.length - state.futureLimit));
    var pastItems = filtered ? parts.past : parts.past.slice(0, state.pastLimit);
    if (!filtered && parts.future.length > futureItems.length) {
      host.appendChild(
        lazyMark(
          "agenda-more-future",
          "Earlier future",
          parts.future.length - futureItems.length
        )
      );
    }
    groupDays(futureItems).forEach(function (g) {
      appendDay(host, g.day, g.rows, today);
    });
    appendDay(host, today, parts.today, today);
    groupDays(pastItems).forEach(function (g) {
      appendDay(host, g.day, g.rows, today);
    });
    if (!filtered && parts.past.length > pastItems.length) {
      host.appendChild(
        lazyMark(
          "agenda-more-past",
          "Older",
          parts.past.length - pastItems.length
        )
      );
    }
    if (
      !filtered &&
      !items.length &&
      !parts.today.length
    ) {
      /* today heading still present */
    }
    bindLazy();
    var scroller = document.querySelector(".agenda-main");
    if (state.anchor && scroller) {
      scroller.scrollTop =
        state.anchor.t + (scroller.scrollHeight - state.anchor.h);
      state.anchor = null;
    } else {
      pinToday();
    }
  }

  function paint() {
    paintCal();
    paintTags();
    paintSchedule();
    paintRailTools();
    publishSurface();
  }

  function railCollapsed() {
    var rail = $("agenda-rail");
    return !!(rail && rail.classList.contains("is-collapsed"));
  }

  function setRail(collapsed) {
    var rail = $("agenda-rail");
    var btn = $("agenda-rail-toggle");
    if (!rail || !btn) return;
    rail.classList.toggle("is-collapsed", !!collapsed);
    btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
    var label = collapsed ? "Expand panel" : "Collapse panel";
    btn.title = label;
    btn.setAttribute("aria-label", label);
    var text = btn.querySelector(".agenda-filter-label");
    if (text) text.textContent = collapsed ? "Expand" : "Collapse";
    try {
      localStorage.setItem("gaius-agenda-rail", collapsed ? "collapsed" : "expanded");
    } catch (e) {}
  }

  function paintRailTools() {
    var cal = $("agenda-ico-cal");
    var badge = $("agenda-ico-cal-badge");
    var search = $("agenda-ico-search");
    if (cal) {
      cal.classList.toggle("has", !!state.day);
      cal.title = state.day ? "Calendar · " + state.day : "Calendar";
    }
    if (badge) {
      if (state.day) {
        badge.hidden = false;
        badge.textContent = String(state.day).slice(8, 10).replace(/^0/, "") || state.day;
      } else {
        badge.hidden = true;
        badge.textContent = "";
      }
    }
    if (search) {
      search.classList.toggle("has", !!state.q.trim());
      search.title = state.q.trim() ? "Search · " + state.q.trim() : "Search";
    }
  }

  function toggleCheck(it, idx, done) {
    var checks = (it.checks || []).map(function (c, i) {
      return { done: i === idx ? done : !!c.done, text: c.text || "" };
    });
    fetch("/api/gaius/v1/agenda/update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: it.path, checks: checks }),
    })
      .then(function (r) {
        return r.text().then(function (t) {
          if (!r.ok) throw new Error(t);
        });
      })
      .then(load)
      .catch(function (e) {
        showError(String(e.message || e));
      });
  }

  function toLocal(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    return (
      d.getFullYear() +
      "-" +
      pad(d.getMonth() + 1) +
      "-" +
      pad(d.getDate()) +
      "T" +
      pad(d.getHours()) +
      ":" +
      pad(d.getMinutes())
    );
  }

  function fromLocal(v) {
    if (!v) return "";
    var d = new Date(v);
    return isNaN(d.getTime()) ? "" : d.toISOString();
  }

  function findByPath(path) {
    for (var i = 0; i < state.items.length; i++) {
      if (state.items[i].path === path) return state.items[i];
    }
    return null;
  }

  function publishSurface() {
    if (!window.GaiusSurface) return;
    window.GaiusSurface.setPage("/agenda");
    window.GaiusSurface.setNearby(
      visibleItems().map(function (it) {
        return {
          kind: it.kind,
          intent: it.intent || "",
          title: it.title,
          day: itemDay(it),
          when: fmtWhen(it),
          with: it.with || "",
        };
      })
    );
    var sessions = visibleItems().filter(function (it) {
      return it.intent === "session";
    });
    if (sessions.length && window.GaiusSurface.setFocus && !editing) {
      /* upcoming session brief sits in nearby; Ask reads it */
    }
  }

  function setSheetMode(mode) {
    sheetMode = mode === "edit" ? "edit" : "view";
    var view = $("agenda-view");
    var form = $("agenda-edit-form");
    var editBtn = $("ed-edit");
    var saveBtn = $("ed-save");
    if (view) view.hidden = sheetMode !== "view";
    if (form) form.hidden = sheetMode !== "edit";
    if (editBtn) editBtn.hidden = sheetMode === "edit";
    if (saveBtn) saveBtn.hidden = sheetMode !== "edit";
    if (sheetMode === "edit" && $("ed-title")) $("ed-title").focus();
  }

  function paintView(it) {
    if ($("view-title")) $("view-title").textContent = it.title || "(untitled)";
    if ($("view-meta")) {
      var bits = [
        it.intent || "brief",
        it.kind,
        it.with ? "with " + it.with : "",
        fmtWhen(it),
        (it.tags || []).join(", "),
      ].filter(Boolean);
      $("view-meta").textContent = bits.join(" · ");
    }
    var host = $("view-body");
    if (!host) return;
    if (window.GaiusMd) window.GaiusMd.renderInto(host, it.body || "");
    else host.textContent = it.body || "";
    host.querySelectorAll("[data-wiki]").forEach(function (btn) {
      btn.addEventListener("click", function (ev) {
        ev.preventDefault();
        hop(btn.getAttribute("data-wiki"));
      });
    });
    if (it.intent === "session" && it.calendar_url) {
      var cal = document.createElement("a");
      cal.className = "agenda-cal-link";
      cal.href = it.calendar_url;
      cal.target = "_blank";
      cal.rel = "noopener";
      cal.textContent = "Add to Google Calendar";
      host.appendChild(cal);
    }
  }

  function fillForm(it) {
    $("ed-kind").textContent = (it.kind || "note") + " · " + (it.intent || "brief");
    $("ed-path").textContent = basename(it.path);
    $("ed-title").value = it.title || "";
    $("ed-body").value = it.body || "";
    $("ed-starts").value = toLocal(it.starts);
    $("ed-ends").value = toLocal(it.ends);
    $("ed-tags").value = (it.tags || []).join(", ");
    $("ed-pin").checked = !!it.pin;
    if ($("ed-intent")) $("ed-intent").value = it.intent || "brief";
    var links = $("ed-links");
    if (!links) return;
    links.replaceChildren();
    if (it.prev) {
      var prev = document.createElement("button");
      prev.type = "button";
      prev.className = "agenda-wiki";
      prev.textContent = "← " + basename(it.prev);
      prev.onclick = function () {
        hop(it.prev);
      };
      links.appendChild(prev);
    }
    if (it.next) {
      var next = document.createElement("button");
      next.type = "button";
      next.className = "agenda-wiki";
      next.textContent = basename(it.next) + " →";
      next.onclick = function () {
        hop(it.next);
      };
      links.appendChild(next);
    }
  }

  function openEditor(it, mode) {
    editing = it;
    if (window.GaiusSurface) {
      window.GaiusSurface.setFocus({
        kind: it.kind,
        intent: it.intent || "",
        title: it.title,
        path: basename(it.path),
        starts: it.starts || "",
        ends: it.ends || "",
        tags: (it.tags || []).join(", "),
        pin: !!it.pin,
        with: it.with || "",
        body: it.body || "",
      });
    }
    $("agenda-editor").hidden = false;
    fillForm(it);
    paintView(it);
    setSheetMode(mode || "view");
  }

  function hop(path) {
    var local = findByPath(path);
    if (local) {
      openEditor(local);
      return;
    }
    fetch("/api/gaius/v1/agenda?path=" + encodeURIComponent(path))
      .then(function (r) {
        return r.text().then(function (t) {
          if (!r.ok) throw new Error(t);
          return JSON.parse(t);
        });
      })
      .then(function (data) {
        if (data.item) openEditor(data.item);
      })
      .catch(function (e) {
        showError(String(e.message || e));
      });
  }

  function closeEditor() {
    $("agenda-editor").hidden = true;
    editing = null;
  }

  function saveEditor() {
    if (!editing) return;
    var tags = $("ed-tags")
      .value.split(",")
      .map(function (s) {
        return s.trim();
      })
      .filter(Boolean);
    fetch("/api/gaius/v1/agenda/update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        path: editing.path,
        title: $("ed-title").value,
        body: $("ed-body").value,
        starts: fromLocal($("ed-starts").value),
        ends: fromLocal($("ed-ends").value),
        tags: tags,
        pin: $("ed-pin").checked,
        intent: ($("ed-intent") && $("ed-intent").value) || editing.intent || "",
      }),
    })
      .then(function (r) {
        return r.text().then(function (t) {
          if (!r.ok) throw new Error(t);
        });
      })
      .then(function () {
        return load().then(function () {
          var again = findByPath(editing && editing.path);
          if (again) openEditor(again, "view");
          else closeEditor();
        });
      })
      .catch(function (e) {
        showError(String(e.message || e));
      });
  }

  function defaultStarts(kind) {
    if (kind !== "event" && kind !== "session") return "";
    var day = state.day || todayKey();
    var p = String(day).split("-");
    if (p.length < 3) return "";
    var d = new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2]), 13, 0, 0);
    if (isNaN(d.getTime())) return "";
    return d.toISOString();
  }

  function create(kind) {
    var intent =
      kind === "session" ? "session" : kind === "list" ? "reminder" : "brief";
    var shape = kind === "session" ? "event" : kind;
    var title =
      kind === "list" ? "List" : kind === "session" ? "Session" : kind === "event" ? "Event" : "Note";
    var body = kind === "list" ? "- [ ] \n" : "";
    fetch("/api/gaius/v1/agenda", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        kind: shape,
        title: title,
        body: body,
        starts: defaultStarts(kind),
        intent: intent,
        with: kind === "session" ? "agents" : "",
        timezone: browserTz(),
      }),
    })
      .then(function (r) {
        return r.text().then(function (t) {
          if (!r.ok) throw new Error(t);
          return JSON.parse(t);
        });
      })
      .then(function (data) {
        $("agenda-fab-menu").hidden = true;
        return load().then(function () {
          if (data.item) openEditor(data.item, "edit");
        });
      })
      .catch(function (e) {
        showError(String(e.message || e));
      });
  }

  function boot() {
    document.querySelectorAll(".agenda-filter").forEach(function (btn) {
      btn.addEventListener("click", function () {
        document.querySelectorAll(".agenda-filter").forEach(function (b) {
          b.classList.toggle("active", b === btn);
        });
        state.kind = btn.getAttribute("data-kind") || "";
        state.windowDays = 14;
        state.futureLimit = 0;
        state.pastLimit = 0;
        state.stickToday = true;
        load();
      });
    });
    $("agenda-fab").addEventListener("click", function (ev) {
      ev.stopPropagation();
      var m = $("agenda-fab-menu");
      m.hidden = !m.hidden;
    });
    $("agenda-fab-menu").addEventListener("click", function (ev) {
      var k = ev.target.getAttribute("data-create");
      if (k) create(k);
    });
    $("ed-close").addEventListener("click", closeEditor);
    $("ed-save").addEventListener("click", saveEditor);
    if ($("ed-edit")) {
      $("ed-edit").addEventListener("click", function () {
        if (editing) setSheetMode("edit");
      });
    }
    $("agenda-editor").addEventListener("click", function (ev) {
      if (ev.target === $("agenda-editor")) closeEditor();
    });
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") {
        if (!$("agenda-editor").hidden) closeEditor();
        $("agenda-fab-menu").hidden = true;
      }
    });
    document.addEventListener("click", function (ev) {
      var menu = $("agenda-fab-menu");
      var fab = $("agenda-fab");
      if (menu.hidden) return;
      if (menu.contains(ev.target) || fab.contains(ev.target)) return;
      menu.hidden = true;
    });
    var q = $("agenda-q");
    if (q) {
      q.addEventListener("input", function () {
        state.q = q.value || "";
        paint();
      });
    }
    var toggle = $("agenda-rail-toggle");
    if (toggle) {
      toggle.addEventListener("click", function () {
        setRail(!railCollapsed());
      });
    }
    var icoCal = $("agenda-ico-cal");
    if (icoCal) {
      icoCal.addEventListener("click", function () {
        setRail(false);
      });
    }
    var icoSearch = $("agenda-ico-search");
    if (icoSearch) {
      icoSearch.addEventListener("click", function () {
        setRail(false);
        var box = $("agenda-q");
        if (box) box.focus();
      });
    }
    try {
      setRail(localStorage.getItem("gaius-agenda-rail") === "collapsed");
    } catch (e) {
      setRail(false);
    }
    var main = document.querySelector(".agenda-main");
    if (main) {
      main.addEventListener(
        "scroll",
        function () {
          state.stickToday = false;
        },
        { passive: true }
      );
    }
    document.addEventListener("keydown", function (ev) {
      if (ev.key !== "[") return;
      var t = ev.target;
      var tag = (t && t.tagName) || "";
      if (tag === "INPUT" || tag === "TEXTAREA" || (t && t.isContentEditable)) return;
      ev.preventDefault();
      setRail(!railCollapsed());
    });
    document.addEventListener("gaius-agenda-upsert", function (ev) {
      var item = ev.detail || {};
      load().then(function () {
        var again = item.path ? findByPath(item.path) : null;
        if (again) openEditor(again, "view");
        else if (item.title) openEditor(item, "view");
      });
    });
    load();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
