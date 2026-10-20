/* The khata chart: week-end cash as bars on ruled lines, the lowest point
   inside each week as a tick, the stress test as a dashed line and the
   reserve as the red rule. Built with DOM calls only (no innerHTML). */
"use strict";

const SVG_NS = "http://www.w3.org/2000/svg";

function svgEl(tag, attrs, text) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, String(v));
  if (text !== undefined) node.textContent = text;
  return node;
}

function niceStep(range) {
  const raw = range / 5;
  const pow = Math.pow(10, Math.floor(Math.log10(raw)));
  const unit = raw / pow;
  const step = unit < 1.5 ? 1 : unit < 3.5 ? 2.5 : unit < 7.5 ? 5 : 10;
  return step * pow;
}

function drawCashChart(container, rows, stressRows, reserve, opts = {}) {
  container.replaceChildren();
  const W = 760, H = 310, m = { l: 74, r: 18, t: 28, b: 52 };
  const values = [];
  rows.forEach((r) => values.push(r.closing, r.low_point));
  (stressRows || []).forEach((r) => values.push(r.closing));
  values.push(reserve, 0);
  let lo = Math.min(...values), hi = Math.max(...values);
  const step = niceStep(hi - Math.min(lo, 0));
  lo = Math.floor(Math.min(lo, 0) / step) * step;
  hi = Math.ceil((hi * 1.04) / step) * step;
  const y = (v) => m.t + (H - m.t - m.b) * (1 - (v - lo) / (hi - lo));
  const n = rows.length;
  const slot = (W - m.l - m.r) / n;
  const barW = Math.min(46, slot * 0.56);
  const cx = (i) => m.l + slot * i + slot / 2;

  const tightest = rows.reduce((best, r) => (best === null || r.headroom < best.headroom ? r : best), null);
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img",
    "aria-label": opts.ariaLabel || "Weekly cash chart" });
  svg.appendChild(svgEl("title", {}, opts.ariaLabel || "Weekly cash chart"));

  for (let v = lo; v <= hi + 1e-6; v += step) {
    svg.appendChild(svgEl("line", { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), class: v === 0 ? "zero" : "gridline" }));
    svg.appendChild(svgEl("text", { x: m.l - 8, y: y(v) + 4, "text-anchor": "end" }, I18N.num(v)));
  }

  rows.forEach((r, i) => {
    const top = Math.max(r.closing, 0), bottom = Math.min(r.closing, 0);
    const cls = r.status === "CASH_SHORTFALL" ? "bar-bad" : r.status === "RESERVE_BREACH" ? "bar-warn" : "bar-ok";
    const bar = svgEl("rect", { x: cx(i) - barW / 2, y: y(top), width: barW, height: Math.max(1, y(bottom) - y(top)), rx: 3, class: cls });
    const tip = `${I18N.weekLabel(r.label)}: ${I18N.t("th_close")} ${I18N.money(r.closing)}; ${I18N.t("th_low")} ${I18N.money(r.low_point)}; ${I18N.t("th_status")} ${I18N.t("st_" + r.status)}`;
    bar.appendChild(svgEl("title", {}, tip));
    svg.appendChild(bar);
    const lowY = y(r.low_point);
    svg.appendChild(svgEl("line", { x1: cx(i) - barW * 0.62, x2: cx(i) + barW * 0.62, y1: lowY, y2: lowY, stroke: "var(--paper)", "stroke-width": 5 }));
    svg.appendChild(svgEl("line", { x1: cx(i) - barW * 0.62, x2: cx(i) + barW * 0.62, y1: lowY, y2: lowY, class: r.low_point < 0 ? "low-bad" : "low" }));
    svg.appendChild(svgEl("text", { x: cx(i), y: H - m.b + 18, "text-anchor": "middle" }, I18N.weekLabel(r.label)));
    svg.appendChild(svgEl("text", { x: cx(i), y: H - m.b + 34, "text-anchor": "middle" }, I18N.dayMonth(r.start)));
    if (tightest && r.index === tightest.index && !opts.hideTightest) {
      svg.appendChild(svgEl("text", { x: cx(i), y: Math.min(y(top), lowY) - 8, "text-anchor": "middle", class: "tight" }, I18N.t("tightest")));
    }
  });

  if (stressRows && stressRows.length) {
    const pts = stressRows.map((r, i) => `${cx(i)},${y(r.closing)}`).join(" ");
    svg.appendChild(svgEl("polyline", { points: pts, class: "stress" }));
    stressRows.forEach((r, i) => {
      const dot = svgEl("circle", { cx: cx(i), cy: y(r.closing), r: 4, class: "stress-dot" });
      dot.appendChild(svgEl("title", {}, `${I18N.t("stress")} ${I18N.weekLabel(r.label)}: ${I18N.money(r.closing)}`));
      svg.appendChild(dot);
    });
  }

  svg.appendChild(svgEl("line", { x1: m.l, x2: W - m.r, y1: y(reserve), y2: y(reserve), class: "reserve" }));
  svg.appendChild(svgEl("text", { x: m.l + 6, y: y(reserve) + 16, "text-anchor": "start", class: "reserve-label" },
    `${I18N.t("legendReserve")} ${I18N.money(reserve)}`));
  container.appendChild(svg);
}
