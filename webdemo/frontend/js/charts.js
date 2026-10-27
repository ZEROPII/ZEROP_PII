// 손으로 그린 SVG 차트 (외부 라이브러리 없음). 선 2px, 표식 8px, 격자는 옅게, 계열은 범례 + 끝 이름표.
import { esc } from "./api.js";

const NS = "http://www.w3.org/2000/svg";

function logTicks(max) {
  return [1, 2, 5, 10, 20, 50, 100, 200, 500].filter((t) => t <= max * 1.05);
}

/**
 * opts: { series:[{key,name,color,points:[[x,y]]}], xMax, yMax, log=true, percent=false,
 *         band:{below, label}, vline:{x,label}, xLabel, yLabel, height=260, fmt }
 */
export function lineChart(el, opts) {
  const W = 760, H = opts.height || 260, m = { l: 52, r: 96, t: 14, b: 38 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const xMax = Math.max(1, opts.xMax);
  const log = opts.log !== false && !opts.percent;
  const yMax = opts.percent ? 1 : Math.max(opts.yMax || 1, 6);
  const x = (v) => m.l + (v / xMax) * iw;
  const y = log
    ? (v) => m.t + ih - (Math.log(Math.max(v, 1)) / Math.log(yMax)) * ih
    : (v) => m.t + ih - (v / yMax) * ih;
  const fmt = opts.fmt || ((v) => (opts.percent ? `${Math.round(v * 100)}%` : String(v)));
  const yt = opts.percent ? [0, 0.25, 0.5, 0.75, 1] : logTicks(yMax);
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(opts.aria || "")}">`;
  // 위반 구간
  if (opts.band && log) {
    const yb = y(opts.band.below);
    s += `<rect x="${m.l}" y="${yb}" width="${iw}" height="${m.t + ih - yb}" fill="#FBEAE6" opacity=".7"/>`;
    s += `<line x1="${m.l}" x2="${m.l + iw}" y1="${yb}" y2="${yb}" stroke="#B83A26" stroke-width="1.5" stroke-dasharray="5 4"/>`;
    s += `<text x="${m.l + 8}" y="${yb + 15}" font-size="12" fill="#B83A26">${esc(opts.band.label)}</text>`;
  }
  // 격자·축
  for (const t of yt) {
    s += `<line x1="${m.l}" x2="${m.l + iw}" y1="${y(t)}" y2="${y(t)}" stroke="#EDF1F6"/>`;
    s += `<text x="${m.l - 8}" y="${y(t) + 4}" font-size="12" fill="#6B7891" text-anchor="end">${fmt(t)}</text>`;
  }
  for (let t = 0; t <= xMax; t++) {
    s += `<text x="${x(t)}" y="${m.t + ih + 18}" font-size="12" fill="#6B7891" text-anchor="middle">${t}</text>`;
  }
  s += `<line x1="${m.l}" x2="${m.l + iw}" y1="${m.t + ih}" y2="${m.t + ih}" stroke="#C9D3E0"/>`;
  if (opts.xLabel) s += `<text x="${m.l + iw / 2}" y="${H - 4}" font-size="12" fill="#43506A" text-anchor="middle">${esc(opts.xLabel)}</text>`;
  if (opts.yLabel) s += `<text x="14" y="${m.t + ih / 2}" font-size="12" fill="#43506A" text-anchor="middle" transform="rotate(-90 14 ${m.t + ih / 2})">${esc(opts.yLabel)}</text>`;
  if (opts.vline) {
    const vx = x(opts.vline.x);
    s += `<line x1="${vx}" x2="${vx}" y1="${m.t}" y2="${m.t + ih}" stroke="#8A97AD" stroke-dasharray="3 4"/>`;
    s += `<text x="${vx - 5}" y="${m.t + ih - 8}" font-size="11.5" fill="#6B7891" text-anchor="end">${esc(opts.vline.label)}</text>`;
  }
  // 선
  const ends = [];
  for (const se of opts.series) {
    const pts = se.points.filter((p) => p[1] != null && (!log || p[1] > 0));
    if (!pts.length) continue;
    const d = pts.map((p, i) => `${i ? "L" : "M"}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join("");
    s += `<path d="${d}" fill="none" stroke="${se.color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"${se.dash ? ` stroke-dasharray="${se.dash}"` : ""}/>`;
    for (const p of pts) s += `<circle cx="${x(p[0])}" cy="${y(p[1])}" r="4" fill="${se.color}" stroke="#fff" stroke-width="2"/>`;
    const last = pts[pts.length - 1];
    ends.push({ y: y(last[1]), x: x(last[0]), name: se.name, color: se.color, v: last[1] });
  }
  // 끝 이름표: 겹치면 아래로 민다
  ends.sort((a, b) => a.x - b.x || a.y - b.y);
  const lastAt = {};
  for (const e of ends) {
    const ly = Math.max(e.y + 4, (lastAt[e.x] ?? -99) + 15);
    lastAt[e.x] = ly;
    s += `<text x="${e.x + 10}" y="${ly}" font-size="12" fill="#15233F">${esc(e.name)} ${esc(fmt(e.v))}</text>`;
  }
  s += `<rect class="hit" x="${m.l}" y="${m.t}" width="${iw}" height="${ih}" fill="transparent"/>`;
  s += `<line class="cross" x1="0" x2="0" y1="${m.t}" y2="${m.t + ih}" stroke="#8A97AD" stroke-width="1" visibility="hidden"/>`;
  s += `</svg>`;
  el.classList.add("chart");
  el.innerHTML = `<div class="legend">${opts.series.map((se) => `<span><i style="background:${se.color}"></i>${esc(se.name)}</span>`).join("")}</div>${s}<div class="tip"></div>`;
  // 마우스 위치의 턴 값
  const svg = el.querySelector("svg"), tip = el.querySelector(".tip"), cross = el.querySelector(".cross");
  svg.querySelector(".hit").addEventListener("mousemove", (ev) => {
    const r = svg.getBoundingClientRect();
    const px = ((ev.clientX - r.left) / r.width) * W;
    const t = Math.max(0, Math.min(xMax, Math.round(((px - m.l) / iw) * xMax)));
    cross.setAttribute("x1", x(t)); cross.setAttribute("x2", x(t)); cross.setAttribute("visibility", "visible");
    const rows = opts.series.map((se) => {
      const p = se.points.find((q) => q[0] === t);
      return p ? `<div class="r"><span><span class="sw" style="background:${se.color}"></span> ${esc(se.name)}</span><b class="num">${esc(fmt(p[1]))}</b></div>` : "";
    }).join("");
    tip.innerHTML = `<b>${esc(opts.tipTitle ? opts.tipTitle(t) : `턴 ${t}`)}</b>${rows || '<span class="muted">값 없음</span>'}`;
    tip.style.display = "block";
    const left = (x(t) / W) * r.width;
    tip.style.left = `${left + (left > r.width * 0.6 ? -tip.offsetWidth - 12 : 12)}px`;
    tip.style.top = `${10}px`;
  });
  svg.querySelector(".hit").addEventListener("mouseleave", () => { tip.style.display = "none"; cross.setAttribute("visibility", "hidden"); });
}

/** 가로 막대: rows [{label, value, max, color, text}] */
export function hBars(rows, max) {
  const mx = max || Math.max(1, ...rows.map((r) => r.value));
  return `<div class="hbars">${rows.map((r) => `<div class="hbar" title="${esc(r.label)}: ${esc(r.text ?? r.value)}">
      <span>${esc(r.label)}</span><div class="bar"><div style="width:${(r.value / mx) * 100}%;${r.color ? `background:${r.color}` : ""}"></div></div>
      <span class="num r">${esc(r.text ?? r.value)}</span></div>`).join("")}</div>`;
}

/** 누적 막대(허용·넓힘·뺌): rows [{label, parts:[{v,color,name}]}] */
export function stackBars(rows) {
  return `<div class="hbars">${rows.map((r) => {
    const tot = r.parts.reduce((a, p) => a + p.v, 0) || 1;
    const supp = r.parts[r.parts.length - 1];
    return `<div class="hbar"><span>${esc(r.label)}</span><div class="stack3">${r.parts.filter((p) => p.v > 0).map((p) =>
      `<div style="width:${(p.v / tot) * 100}%;background:${p.color}" title="${esc(p.name)} ${p.v}건 (${((p.v / tot) * 100).toFixed(1)}%)"></div>`).join("")}</div>
      <span class="num">${((supp.v / tot) * 100).toFixed(0)}%</span></div>`;
  }).join("")}</div>`;
}
