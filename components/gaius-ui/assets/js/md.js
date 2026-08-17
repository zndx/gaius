/* Shared markdown + Kumo OHLC for Ask and Agenda view. */
(function (global) {
  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function ohlcSvg(bars) {
    var w = 300;
    var h = 132;
    var pad = 8;
    var n = (bars || []).length;
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
      var yo = y(o);
      var yc = y(c);
      parts.push(
        '<line x1="' + x + '" x2="' + x + '" y1="' + y(hi) + '" y2="' + y(lo) + '" stroke="' + color + '" stroke-width="1"/>'
      );
      parts.push(
        '<rect x="' + (x - bw / 2) + '" y="' + Math.min(yo, yc) + '" width="' + bw +
          '" height="' + Math.max(1, Math.abs(yc - yo)) + '" fill="' + color + '"/>'
      );
    });
    parts.push("</svg>");
    return parts.join("");
  }

  function artifactHtml(obj) {
    if (!obj || typeof obj !== "object") return "";
    var type = obj.type || obj.kind || "";
    if (type === "agenda" || obj.action === "create" || obj.action === "created") {
      var when = [obj.starts || "", obj.ends || ""].filter(Boolean).join(" – ");
      return (
        '<div class="ask-agenda-card">' +
        '<div class="ask-art-head">' +
        escapeHtml(obj.title || "Agenda") +
        "</div>" +
        '<div class="ask-art-meta">' +
        escapeHtml(
          [obj.intent || obj.kind || "", when, obj.with ? "with " + obj.with : ""]
            .filter(Boolean)
            .join(" · ")
        ) +
        "</div></div>"
      );
    }
    if (type === "ohlc") {
      var svg = ohlcSvg(obj.bars || []);
      if (!svg) return "";
      var last = (obj.bars || [])[(obj.bars || []).length - 1];
      return (
        '<figure class="ask-artifact agenda-art">' +
        '<div class="ask-art-head"></div>'.replace(
          "></div>",
          ">" + escapeHtml(obj.title || obj.symbol || "OHLC") + "</div>"
        ) +
        '<div class="ask-art-chart">' + svg + "</div>" +
        '<figcaption class="ask-art-meta">' +
        escapeHtml((obj.symbol || "") + (last ? " · " + last.t + "  c " + last.c : "")) +
        "</figcaption></figure>"
      );
    }
    if (obj.body) {
      return '<div class="ask-md">' + renderInline(obj.body) + "</div>";
    }
    return "";
  }

  function renderInline(src) {
    var t = escapeHtml(src || "");
    t = t.replace(/`([^`]+)`/g, "<code>$1</code>");
    t = t.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    t = t.replace(
      /!\[([^\]]*)\]\((https?:[^)\s]+)\)/g,
      '<img class="agenda-md-img" src="$2" alt="$1" />'
    );
    t = t.replace(
      /\[([^\]]+)\]\((https?:[^)\s]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener">$1</a>'
    );
    t = t.replace(
      /\[\[([^\]|]+)\|([^\]]+)\]\]/g,
      '<button type="button" class="agenda-wiki" data-wiki="$1">$2</button>'
    );
    t = t.replace(
      /\[\[([^\]]+)\]\]/g,
      '<button type="button" class="agenda-wiki" data-wiki="$1">$1</button>'
    );
    return t;
  }

  function renderMd(src) {
    var raw = String(src || "");
    var fences = [];
    raw = raw.replace(/:::gaius-artifact\s*([\s\S]*?):::/g, function (_, json) {
      var i = fences.length;
      var html = "";
      try {
        html = artifactHtml(JSON.parse(json));
      } catch (e) {
        html = "<pre class=\"agenda-md-pre\">" + escapeHtml(json.trim()) + "</pre>";
      }
      fences.push(html);
      return "\n%%FENCE" + i + "%%\n";
    });
    raw = raw.replace(/```(?:json)?\s*(\{[\s\S]*?\})\s*```/g, function (_, json) {
      try {
        var obj = JSON.parse(json);
        if (obj && (obj.type === "ohlc" || obj.kind === "ohlc")) {
          var i = fences.length;
          fences.push(artifactHtml(obj));
          return "\n%%FENCE" + i + "%%\n";
        }
      } catch (e) {}
      return _;
    });
    var lines = raw.split("\n");
    var out = [];
    var i = 0;
    while (i < lines.length) {
      var line = lines[i];
      var fm = line.match(/^%%FENCE(\d+)%%$/);
      if (fm) {
        out.push(fences[Number(fm[1])] || "");
        i += 1;
        continue;
      }
      if (/^\s*\|/.test(line)) {
        var rows = [];
        while (i < lines.length && /^\s*\|/.test(lines[i])) {
          var cells = lines[i].replace(/^\s*\|/, "").replace(/\|\s*$/, "").split("|");
          if (!/^\s*\|?\s*:?-/.test(lines[i])) {
            rows.push(cells.map(function (c) { return c.trim(); }));
          }
          i += 1;
        }
        if (rows.length) {
          var thead = rows.shift();
          out.push("<table class=\"agenda-md-table\"><thead><tr>" +
            thead.map(function (c) { return "<th>" + renderInline(c) + "</th>"; }).join("") +
            "</tr></thead><tbody>" +
            rows.map(function (r) {
              return "<tr>" + r.map(function (c) { return "<td>" + renderInline(c) + "</td>"; }).join("") + "</tr>";
            }).join("") +
            "</tbody></table>");
        }
        continue;
      }
      if (/^### /.test(line)) {
        out.push("<h4>" + renderInline(line.slice(4)) + "</h4>");
        i += 1;
        continue;
      }
      if (/^## /.test(line)) {
        out.push("<h3>" + renderInline(line.slice(3)) + "</h3>");
        i += 1;
        continue;
      }
      if (/^# /.test(line)) {
        out.push("<h3>" + renderInline(line.slice(2)) + "</h3>");
        i += 1;
        continue;
      }
      if (/^- \[([ xX])\] /.test(line)) {
        var items = [];
        while (i < lines.length && /^- \[([ xX])\] /.test(lines[i])) {
          var m = lines[i].match(/^- \[([ xX])\] (.*)$/);
          items.push(
            '<li class="' + (m[1] !== " " ? "done" : "") + '">' +
              '<input type="checkbox" disabled' + (m[1] !== " " ? " checked" : "") + " /> " +
              renderInline(m[2]) +
              "</li>"
          );
          i += 1;
        }
        out.push('<ul class="agenda-checks">' + items.join("") + "</ul>");
        continue;
      }
      if (/^- /.test(line)) {
        var lis = [];
        while (i < lines.length && /^- /.test(lines[i])) {
          lis.push("<li>" + renderInline(lines[i].slice(2)) + "</li>");
          i += 1;
        }
        out.push("<ul>" + lis.join("") + "</ul>");
        continue;
      }
      if (!line.trim()) {
        i += 1;
        continue;
      }
      var para = [line];
      i += 1;
      while (i < lines.length && lines[i].trim() && !/^[#|\-]/.test(lines[i]) && !/^%%FENCE/.test(lines[i])) {
        para.push(lines[i]);
        i += 1;
      }
      out.push("<p>" + renderInline(para.join(" ")) + "</p>");
    }
    return out.join("");
  }

  function renderInto(el, src) {
    if (!el) return;
    el.innerHTML = renderMd(src);
  }

  global.GaiusMd = {
    escapeHtml: escapeHtml,
    ohlcSvg: ohlcSvg,
    renderMd: renderMd,
    renderInto: renderInto,
  };
})(window);
