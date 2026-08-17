(function () {
  var toggle = document.getElementById("waffle-toggle");
  var rail = document.getElementById("waffle-rail");
  var list = document.getElementById("waffle-list");
  var empty = document.getElementById("waffle-empty");
  var closeBtn = document.getElementById("waffle-close");
  if (!toggle || !rail || !list) return;

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
      a.href = it.primary_ui;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      var name = document.createElement("span");
      name.className = "waffle-project";
      name.textContent = it.project || it.engine_target || "peer";
      var url = document.createElement("span");
      url.className = "waffle-url";
      url.textContent = it.primary_ui;
      a.appendChild(name);
      a.appendChild(url);
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
