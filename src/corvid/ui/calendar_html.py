"""The HTML/JS for the WebView month calendar (an accessible ARIA grid).

Python drives it by calling ``setMonth({...})`` via RunScript; the page reports
selection/activation/month changes back through ``window.corvid.postMessage``.
The grid follows the WAI-ARIA date-grid pattern: ``role="grid"`` with a roving
tabindex over ``gridcell`` days, each with an ``aria-label`` naming the date and
its event count, so NVDA announces e.g. "Monday, July 14 2026, 2 events".
"""

from __future__ import annotations

CALENDAR_HTML = r"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8">
<style>
  :root { color-scheme: light dark; }
  body { font-family: "Segoe UI", sans-serif; margin: 0; padding: 8px;
         background: Canvas; color: CanvasText; }
  .bar { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
  .bar button { font: inherit; padding: 4px 10px; cursor: pointer; }
  h1 { font-size: 1.1rem; margin: 0; flex: 1; text-align: center; }
  table { border-collapse: collapse; width: 100%; }
  th { font-size: .8rem; padding: 4px; opacity: .7; }
  td { text-align: center; padding: 0; }
  .day { width: 100%; aspect-ratio: 1 / 1; display: flex; flex-direction: column;
         align-items: center; justify-content: center; border: 1px solid transparent;
         border-radius: 6px; cursor: pointer; position: relative; }
  .day:hover { background: rgba(127,127,127,.15); }
  .day.other { opacity: .35; }
  .day.today { font-weight: bold; box-shadow: inset 0 0 0 1px currentColor; }
  .day[aria-selected="true"] { background: #d9a400; color: #1a1a1a; }
  .day:focus { outline: 3px solid #4a90d9; outline-offset: -2px; }
  .dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor;
         margin-top: 2px; }
  .day[aria-selected="true"] .dot { background: #1a1a1a; }
</style></head>
<body>
  <div class="bar">
    <button id="prev" aria-label="Previous month">&#9664;</button>
    <h1 id="title" aria-live="polite">Calendar</h1>
    <button id="next" aria-label="Next month">&#9654;</button>
  </div>
  <table role="grid" aria-labelledby="title">
    <thead><tr id="head" role="row"></tr></thead>
    <tbody id="grid"></tbody>
  </table>
<script>
  var MONTHS = ["January","February","March","April","May","June","July",
                "August","September","October","November","December"];
  var WD_SHORT = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];
  var WD_LONG = ["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"];
  var state = { year: 2000, month: 1, selected: "", today: "", counts: {} };

  function post(msg) {
    try { window.corvid.postMessage(JSON.stringify(msg)); } catch (e) {}
  }
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function iso(y, m, d) { return y + "-" + pad(m) + "-" + pad(d); }

  function head() {
    var tr = document.getElementById("head"), h = "";
    for (var i = 0; i < 7; i++)
      h += '<th role="columnheader" abbr="' + WD_LONG[i] + '">' + WD_SHORT[i] + '</th>';
    tr.innerHTML = h;
  }

  function render() {
    document.getElementById("title").textContent = MONTHS[state.month - 1] + " " + state.year;
    var first = new Date(state.year, state.month - 1, 1);
    var startDow = first.getDay();
    var daysIn = new Date(state.year, state.month, 0).getDate();
    var body = document.getElementById("grid");
    body.innerHTML = "";
    var day = 1 - startDow;
    for (var w = 0; w < 6; w++) {
      if (day > daysIn) break;
      var tr = document.createElement("tr");
      tr.setAttribute("role", "row");
      for (var c = 0; c < 7; c++, day++) {
        var td = document.createElement("td");
        td.setAttribute("role", "gridcell");
        var cur = new Date(state.year, state.month - 1, day);
        var y = cur.getFullYear(), m = cur.getMonth() + 1, d = cur.getDate();
        var ds = iso(y, m, d);
        var inMonth = (m === state.month && y === state.year);
        var count = inMonth ? (state.counts[String(d)] || 0) : 0;
        var cell = document.createElement("div");
        cell.className = "day" + (inMonth ? "" : " other") + (ds === state.today ? " today" : "");
        cell.setAttribute("data-date", ds);
        cell.setAttribute("tabindex", ds === state.selected ? "0" : "-1");
        cell.setAttribute("aria-selected", ds === state.selected ? "true" : "false");
        var label = WD_LONG[cur.getDay()] + ", " + MONTHS[m - 1] + " " + d + " " + y +
                    (count ? (", " + count + " event" + (count === 1 ? "" : "s")) : ", no events");
        cell.setAttribute("aria-label", label);
        cell.innerHTML = d + (count ? '<span class="dot" aria-hidden="true"></span>' : "");
        td.appendChild(cell);
        tr.appendChild(td);
      }
      body.appendChild(tr);
    }
    var sel = body.querySelector('.day[aria-selected="true"]');
    if (sel) sel.focus();
  }

  function selectDate(ds, focus) {
    state.selected = ds;
    render();
    post({ type: "select", date: ds });
  }

  function move(days, months) {
    var d = new Date(state.selected + "T00:00:00");
    if (months) d.setMonth(d.getMonth() + months);
    if (days) d.setDate(d.getDate() + days);
    var y = d.getFullYear(), m = d.getMonth() + 1;
    var nds = iso(y, m, d.getDate());
    if (m === state.month && y === state.year) selectDate(nds, true);
    else post({ type: "month", year: y, month: m, selected: nds });
  }

  document.addEventListener("keydown", function (e) {
    var k = e.key;
    if (k === "ArrowLeft") move(-1, 0);
    else if (k === "ArrowRight") move(1, 0);
    else if (k === "ArrowUp") move(-7, 0);
    else if (k === "ArrowDown") move(7, 0);
    else if (k === "PageUp") move(0, -1);
    else if (k === "PageDown") move(0, 1);
    else if (k === "Home") {
      var d = new Date(state.selected + "T00:00:00"); move(-d.getDay(), 0);
    }
    else if (k === "End") {
      var d2 = new Date(state.selected + "T00:00:00"); move(6 - d2.getDay(), 0);
    }
    else if (k === "Enter" || k === " ") post({ type: "activate", date: state.selected });
    else return;
    e.preventDefault();
  });
  document.addEventListener("click", function (e) {
    var cell = e.target.closest(".day");
    if (cell) selectDate(cell.getAttribute("data-date"), true);
  });
  document.addEventListener("dblclick", function (e) {
    var cell = e.target.closest(".day");
    if (cell) post({ type: "activate", date: cell.getAttribute("data-date") });
  });
  document.getElementById("prev").addEventListener("click", function () { move(0, -1); });
  document.getElementById("next").addEventListener("click", function () { move(0, 1); });

  window.setMonth = function (data) { state = data; head(); render(); };
  post({ type: "ready" });
</script></body></html>
"""
