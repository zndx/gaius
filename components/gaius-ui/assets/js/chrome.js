(function () {
  var toggle = document.getElementById("waffle-toggle");
  var rail = document.getElementById("waffle-rail");
  var list = document.getElementById("waffle-list");
  var empty = document.getElementById("waffle-empty");
  var closeBtn = document.getElementById("waffle-close");
  if (!toggle || !rail || !list) return;

  function isIpHost(h) {
    if (!h) return false;
    if (h.indexOf(":") >= 0) return true;
    return /^\d{1,3}(\.\d{1,3}){3}$/.test(h);
  }

  function hrefForBrowser(url) {
    var browse = window.location.hostname;
    if (!url || !isIpHost(browse)) return url;
    try {
      var u = new URL(url, window.location.origin);
      u.hostname = browse;
      if (window.location.protocol) u.protocol = window.location.protocol;
      return u.toString();
    } catch (e) {
      return url;
    }
  }

  function itemTitle(it) {
    if (it && it.title) return it.title;
    var p = (it && it.project) || "";
    if (!p) return "Peer";
    return p.replace(/[-_]/g, " ").replace(/\b\w/g, function (c) {
      return c.toUpperCase();
    });
  }

  function setOpen(open) {
    rail.hidden = !open;
    toggle.setAttribute("aria-pressed", open ? "true" : "false");
    toggle.classList.toggle("active", open);
  }

  function render(items) {
    list.innerHTML = "";
    var rows = items || [];
    if (empty) empty.hidden = rows.length > 0;
    rows.forEach(function (it) {
      var li = document.createElement("li");
      var a = document.createElement("a");
      a.href = hrefForBrowser(it.primary_ui);
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.textContent = itemTitle(it);
      a.className = "waffle-project";
      li.appendChild(a);
      list.appendChild(li);
    });
  }

  async function load() {
    try {
      var r = await fetch("/api/gaius/v1/federation/surfaces");
      var data = await r.json();
      if (!r.ok || data.error) {
        render([]);
        if (empty) {
          empty.hidden = false;
          empty.textContent = data.error || "Federation surfaces unreachable";
        }
        return;
      }
      render(data.items || []);
    } catch (e) {
      render([]);
      if (empty) {
        empty.hidden = false;
        empty.textContent = "Federation surfaces unreachable";
      }
    }
  }

  toggle.addEventListener("click", function () {
    var open = rail.hidden;
    setOpen(open);
    if (open) load();
  });
  if (closeBtn) closeBtn.addEventListener("click", function () { setOpen(false); });
})();
