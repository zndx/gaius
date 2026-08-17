(function () {
  function cell(ch, cls) {
    var td = document.createElement("td");
    td.textContent = ch;
    if (cls) td.className = cls;
    return td;
  }

  function paintGrid(table, n, paint) {
    table.replaceChildren();
    for (var y = 0; y < n; y++) {
      var tr = document.createElement("tr");
      for (var x = 0; x < n; x++) tr.appendChild(paint(x, y));
      table.appendChild(tr);
    }
  }

  function hoshi(x, y) {
    return [3, 9, 15].indexOf(x) >= 0 && [3, 9, 15].indexOf(y) >= 0;
  }

  function render(board) {
    var main = document.getElementById("main-grid");
    var loc = document.getElementById("location");
    if (!main) return;
    var cx = (board.cursor && board.cursor[0]) || 9;
    var cy = (board.cursor && board.cursor[1]) || 9;
    var target = board.tenuki_target;
    var visited = {};
    (board.tenuki_visited || []).forEach(function (p) {
      visited[p[0] + "," + p[1]] = true;
    });
    var curv = board.curvature;
    paintGrid(main, 19, function (x, y) {
      var cls = [];
      var ch = hoshi(x, y) ? "+" : "·";
      if (curv && curv[y] && typeof curv[y][x] === "number") {
        if (curv[y][x] >= 0.6) cls.push("kappa-pos");
        else if (curv[y][x] >= 0.2) cls.push("kappa-neg");
        if (curv[y][x] > 0) ch = "●";
      }
      if (visited[x + "," + y]) {
        ch = "∘";
        cls.push("tenuki-visited");
      }
      if (target && target[0] === x && target[1] === y) {
        ch = "☆";
        cls.push("tenuki-target");
      }
      if (x === cx && y === cy) cls.push("cursor");
      return cell(ch, cls.join(" "));
    });
    [9, 9].forEach(function () {});
    paintGrid(document.getElementById("minigrid-embed"), 9, function () {
      return cell("·");
    });
    paintGrid(document.getElementById("minigrid-iso"), 9, function () {
      return cell("·");
    });
    if (loc) {
      loc.textContent =
        "◉ [" +
        cx +
        "," +
        cy +
        "] │ κ " +
        (board.kappa == null ? "—" : board.kappa) +
        " │ tenuki " +
        (target ? target[0] + "," + target[1] : "—");
    }
  }

  fetch("/api/gaius/v1/board")
    .then(function (r) {
      if (!r.ok) throw new Error("board " + r.status);
      return r.json();
    })
    .then(render)
    .catch(function (err) {
      var loc = document.getElementById("location");
      if (loc) loc.textContent = String(err);
    });
})();
