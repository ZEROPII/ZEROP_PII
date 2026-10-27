// 보안 관제 화면: 같은 대화를 C0·C1·C1S 세 조건으로 나란히 본다 (GET /api/sessions/{id}/security)
import { api, ARM_HEX, ARM_NAME, esc, h, kChip, kStatus, state, toast } from "./api.js";
import { lineChart } from "./charts.js";

const ARMS = ["C0", "C1", "C1S"];
const MODE = { RAW: ["그대로", "info"], REWRITTEN: ["고침", "c1"], REWRITTEN_FALLBACK: ["고침(치환)", "c1"], REFUSAL: ["거절", "bad"], REFUSAL_EXTRACTION_FAILED: ["거절(추출 실패)", "bad"] };
const ACT = { allow: ["그대로", "info"], generalize: ["넓힘", "c1"], suppress: ["뺌", "gray"] };
const ui = { data: null, sel: null };

export async function mount(root) {
  root.innerHTML = `
  <div class="stack">
    <section class="card">
      <div class="toolbar">
        <div class="info" id="sinfo"><span class="muted">대화를 고르거나 새로 시작하세요.</span></div>
        <div class="spacer" style="flex:1"></div>
        <select id="ssel" class="in" style="width:auto"></select>
        <button class="btn ghost" id="one">퍼저로 1턴</button>
        <button class="btn" id="all">퍼저로 끝까지</button>
      </div>
      <div class="toolbar" style="border-top:1px solid var(--line-2)">
        <span class="small muted">새 대화</span>
        <select id="npt" class="in" style="width:300px"></select>
        <select id="nprof" class="in" style="width:auto"><option value="staged">단계 공개형</option><option value="full">전면 공개형</option></select>
        <select id="nfz" class="in" style="width:auto"><option value="uniform">균등 선택 (통제)</option><option value="feedback">k 피드백 선택 (fuzzer/feedback.py)</option></select>
        <button class="btn ghost" id="new">시작</button>
      </div>
    </section>
    <div class="armcards" id="armcards"></div>
    <div class="row">
      <section class="card" style="flex:1.35">
        <div class="card-h"><h2>사례 A 후보 수 k</h2><span class="sub">턴별 · 로그 눈금 · 사례 A = 사례 검색 답에서 처음 나온 사례</span></div>
        <div class="card-b" id="chart"></div>
      </section>
      <section class="card">
        <div class="card-h"><h2>사례별 현재 k</h2><span class="sub">정답 환자와 대조한 Validated k 포함 · 관제 전용</span></div>
        <div id="casetab"></div>
      </section>
    </div>
    <section class="card">
      <div class="card-h"><h2>턴별 기록</h2><span class="sub">행을 누르면 원 응답·공개 응답·Defender 판정이 열립니다</span></div>
      <div id="turns"></div>
    </section>
    <div class="note">
      <b>읽는 법.</b> 세 조건은 같은 질문을 받습니다(질문은 의료진 화면이나 퍼저가 고름). C0은 원 응답을 그대로, C1은 사례마다 앞서 공개된 값을 모두 더해(누적 State),
      C1S는 매 턴 빈 State로 판정합니다. Defender 규칙: 공개 뒤 k &gt; ${state.meta.generalize_threshold}이면 그대로, 원래 값으로 k ≤ ${state.meta.suppress_threshold}이면 바로 빼고,
      그 사이면 상위 개념으로 올리며 처음 k &gt; ${state.meta.generalize_threshold}(없으면 k &gt; ${state.meta.suppress_threshold})가 되는 값으로 넓힙니다. 위반은 사례 A의 k가 1 이상 ${state.meta.k_req} 미만인 상태입니다.
      대상 AI는 ${esc(state.meta.target)}입니다.
    </div>
  </div>`;
  const npt = root.querySelector("#npt");
  npt.innerHTML = state.patients.map((p) => `<option value="${p.trial_id}">${p.trial_id} · ${esc(p.qtype_label)} · ${esc(p.panel[0].value)} · ${esc(p.panel[1].value)}</option>`).join("");
  npt.value = "T0014";
  root.querySelector("#new").addEventListener("click", async () => {
    try {
      const { id } = await api("/api/sessions", { method: "POST", body: { trial_id: npt.value, profile: root.querySelector("#nprof").value, fuzzer: root.querySelector("#nfz").value } });
      state.setSession(id); ui.sel = null; await refresh();
    } catch (e) { toast(e.message); }
  });
  root.querySelector("#ssel").addEventListener("change", (e) => { state.setSession(e.target.value); ui.sel = null; refresh(); });
  root.querySelector("#one").addEventListener("click", () => act(`/api/sessions/${state.sessionId}/turns`, { arm: state.arm }));
  root.querySelector("#all").addEventListener("click", () => act(`/api/sessions/${state.sessionId}/run?arm=${state.arm}`));
  await refresh();
}

async function act(path, body) {
  if (!state.sessionId) return toast("먼저 대화를 시작하세요.");
  try { await api(path, { method: "POST", body }); await refresh(); } catch (e) { toast(e.message); }
}

export async function refresh() {
  let sessions = [];
  try { sessions = await api("/api/sessions", { quiet: true }); } catch (e) { toast(e.message); }
  const ssel = document.getElementById("ssel");
  if (!ssel) return;
  if (state.sessionId && !sessions.find((s) => s.id === state.sessionId)) state.setSession(null);
  if (!state.sessionId && sessions.length) state.setSession(sessions[sessions.length - 1].id);
  ssel.innerHTML = sessions.length ? sessions.map((s) => `<option value="${s.id}">${s.id} · ${s.trial_id} · ${esc(s.qtype_label)} · ${esc(s.profile_label)} · ${esc(s.fuzzer_label)} · ${s.turn}턴</option>`).join("")
    : `<option value="">대화 없음</option>`;
  if (state.sessionId) ssel.value = state.sessionId;
  ["one", "all"].forEach((id) => (document.getElementById(id).disabled = !state.sessionId));
  if (!state.sessionId) { ui.data = null; renderEmpty(); return; }
  try { ui.data = await api(`/api/sessions/${state.sessionId}/security`, { quiet: true }); } catch (e) { toast(e.message); return; }
  render();
}

function renderEmpty() {
  if (!document.getElementById("armcards")) return;
  document.getElementById("armcards").innerHTML = `<section class="card" style="grid-column:1/-1"><div class="empty">대화가 없습니다. 위에서 새 대화를 시작하세요. T0014를 고르고 “퍼저로 끝까지”를 누르면 슬라이드 18의 대화가 재현됩니다.</div></section>`;
  ["chart", "casetab", "turns"].forEach((id) => (document.getElementById(id).innerHTML = ""));
}

function render() {
  const d = ui.data;
  if (!document.getElementById("armcards")) return;          // 다른 화면으로 옮긴 뒤 늦게 온 응답
  document.getElementById("sinfo").innerHTML = `<b>${esc(d.id)}</b><span class="tag">${esc(d.trial_id)}</span><span class="tag">${esc(d.qtype_label)} 조회</span>
    <span class="tag">${esc(d.panel[0].value)} · ${esc(d.panel[1].value)}</span><span class="tag">${esc(d.profile_label)}</span><span class="tag">${esc(d.fuzzer_label)}</span>
    <span class="muted">질문 ${d.turn}/${d.budget} · 퍼저 기준 조건 ${esc(state.arm)}</span>`;
  renderArmCards(d);
  renderChart(d);
  renderCaseTable(d);
  renderTurns(d);
}

function renderArmCards(d) {
  document.getElementById("armcards").innerHTML = ARMS.map((a) => {
    const x = d.arms[a];
    const ks = x.k_series[x.case_A] || [];
    const k = ks.length ? ks[ks.length - 1][1] : d.p_ref;
    const s = kStatus(k, d.k_req);
    const dec = x.decisions || {};
    const modes = Object.entries(x.release_modes).map(([m, n]) => `${(MODE[m] || [m])[0]} ${n}`).join(" · ");
    return `<section class="card armcard ${a}">
      <h3><span>${esc(ARM_NAME[a])}</span><span class="chip ${s.cls}">${s.label}</span></h3>
      <div class="big num">k ${k}<small>사례 A (${esc(x.case_A || "-")}) 지금 후보 수</small></div>
      <dl>
        <dt>사례 A 첫 위반</dt><dd>${x.first_violation_A == null ? "없음" : `턴 ${x.first_violation_A}`}</dd>
        <dt>위반에 들어간 사례</dt><dd>${x.violated_cases.length} / 5${x.violated_cases.length ? ` <span class="muted small">(${x.violated_cases.join(", ")})</span>` : ""}</dd>
        <dt>공개 단서 유지율</dt><dd>${x.utility == null ? "–" : x.utility.toFixed(2)}</dd>
        <dt>Defender 판정</dt><dd>${a === "C0" ? '<span class="muted">거치지 않음</span>' : `그대로 ${dec.allow || 0} · 넓힘 ${dec.generalize || 0} · 뺌 ${dec.suppress || 0}`}</dd>
        <dt>공개 방식</dt><dd class="small">${esc(modes)}</dd>
      </dl></section>`;
  }).join("");
}

function renderChart(d) {
  const series = ARMS.map((a) => ({ key: a, name: a, color: ARM_HEX[a], points: d.arms[a].k_series[d.arms[a].case_A] || [] }));
  const maxK = Math.max(10, ...series.flatMap((s) => s.points.map((p) => p[1])));
  lineChart(document.getElementById("chart"), {
    series, xMax: Math.max(d.budget, d.turn), yMax: Math.min(d.p_ref, maxK * 1.3), band: { below: d.k_req, label: `위반 구간 k < ${d.k_req}` },
    xLabel: "턴 (0 = 사례 검색)", yLabel: "후보 수 k", aria: "조건별 사례 A 후보 수 변화",
  });
}

function renderCaseTable(d) {
  const refs = d.retrieval.map((r) => r.ref);
  document.getElementById("casetab").innerHTML = `<table class="t"><thead><tr><th>사례</th><th>정답 환자</th>${ARMS.map((a) => `<th>${a}</th>`).join("")}</tr></thead><tbody>
    ${refs.map((ref, i) => `<tr><td><b>${esc(ref)}</b>${ref === d.arms.C1.case_A ? ' <span class="chip info">A</span>' : ""}</td>
      <td class="mono small">${esc(d.retrieval[i].patient)}<br><span class="muted">유사도 ${d.retrieval[i].score}</span></td>
      ${ARMS.map((a) => {
        const ks = d.arms[a].k_series[ref] || [];
        const k = ks.length ? ks[ks.length - 1][1] : d.p_ref;
        const v = d.arms[a].validation[ref];
        return `<td><div class="cellk">${kChip(k, d.k_req)}${v ? `<span class="small muted">k_val ${v.k_val}${v.flag ? ` · ${esc(v.flag)}` : ""}</span>` : ""}</div></td>`;
      }).join("")}</tr>`).join("")}
  </tbody></table>`;
}

function turnOf(d, a, n) { return d.arms[a].turns.find((t) => t.turn === n); }

function renderTurns(d) {
  const rows = d.steps.map((s) => {
    const first = ARMS.map((a) => turnOf(d, a, s.turn)).find(Boolean);
    const tags = s.turn === 0 ? '<span class="tag">사례 검색</span>' : [first?.target_qi && state.meta.attributes[first.target_qi], first?.objective === "SPECIFICITY_REFINEMENT" ? "더 자세히" : first?.objective ? "처음 묻기" : null,
      first?.scope === "GROUP" ? "사례 전체" : first?.scope ? "한 사례" : null, s.picked_by === "clinician" ? "의료진" : s.picked_by?.startsWith("fuzzer") ? "퍼저" : null]
      .filter(Boolean).map((x) => `<span class="tag">${esc(x)}</span>`).join(" ");
    const cells = ARMS.map((a) => {
      const st = s.arms[a];
      if (st.status !== "ANSWERED") return `<td><span class="chip gray">건너뜀</span><div class="small muted">${esc(st.note || "")}</div></td>`;
      const t = turnOf(d, a, s.turn);
      const A = d.arms[a].case_A;
      const k = t.cases[A]?.k, kr = t.cases[A]?.k_if_raw;
      const m = MODE[t.mode] || [t.mode, "gray"];
      return `<td><div class="cellk"><span><span class="chip ${m[1]}">${m[0]}</span> ${kChip(k, d.k_req)}</span>
        ${kr != null && kr !== k ? `<span class="small muted">원 응답이었다면 k ${kr}</span>` : ""}</div></td>`;
    }).join("");
    return `<tr class="click ${ui.sel === s.turn ? "on" : ""}" data-t="${s.turn}"><td class="num">${s.turn}</td><td>${esc(first?.question || "")}<div style="margin-top:4px">${tags}</div></td>${cells}</tr>
      ${ui.sel === s.turn ? `<tr><td colspan="5" style="padding:0">${detail(d, s.turn)}</td></tr>` : ""}`;
  }).join("");
  document.getElementById("turns").innerHTML = `<table class="t"><thead><tr><th>턴</th><th>질문</th>${ARMS.map((a) => `<th style="width:19%">${esc(ARM_NAME[a])}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table>`;
  document.querySelectorAll("#turns tr.click").forEach((tr) => tr.addEventListener("click", () => {
    const n = Number(tr.dataset.t); ui.sel = ui.sel === n ? null : n; renderTurns(d);
  }));
}

function detail(d, n) {
  return `<div class="detail">${ARMS.map((a) => {
    const t = turnOf(d, a, n);
    if (!t) return `<div class="col"><h4>${esc(ARM_NAME[a])}</h4><div class="sec muted">이 턴을 건너뛰었습니다.</div></div>`;
    const rl = t.raw_lines, pl = t.lines;
    const same = rl.length === pl.length;
    const cmp = rl.map((r, i) => {
      if (!r.case) return "";
      const p = same ? pl[i] : null;
      const chg = p && p.value !== r.value;
      return `<span class="c">${esc(r.case)}</span><span class="x ${chg ? "chg" : ""}">${esc(r.field.replace(/^\[기록\d+\]\s*/, ""))}: ${esc(r.value)}${chg ? ` → <b>${esc(p.value)}</b>` : ""}</span>`;
    }).join("");
    const decs = (t.decisions || []).filter((p) => p.items.length);
    const decHtml = a === "C0" ? '<span class="muted">C0은 Defender를 거치지 않습니다.</span>'
      : decs.length ? `<table class="dec"><tr><th>사례</th><th>단서</th><th>원래 값</th><th>판정</th><th class="r">k</th></tr>${decs.flatMap((p) => p.items.map((it) =>
        `<tr><td>${esc(p.case)}</td><td>${esc(it.attribute)}</td><td>${esc(it.raw_value)}</td><td><span class="chip ${ACT[it.action][1]}">${ACT[it.action][0]}</span>${it.to_label ? ` ${esc(it.to_label)}` : ""}</td><td class="r num">${it.k_raw}</td></tr>`)).join("")}</table>
        <div class="small muted" style="margin-top:4px">${decs.map((p) => `${esc(p.case)}: 판정 전 k ${p.k_before} → 그대로 내면 ${p.k_projected} → 판정 뒤 ${p.k_final}`).join("<br>")}</div>`
      : '<span class="muted">판정할 공개가 없습니다.</span>';
    const m = MODE[t.mode] || [t.mode, "gray"];
    return `<div class="col"><h4><span>${esc(ARM_NAME[a])}</span><span class="chip ${m[1]}">${m[0]}</span></h4>
      <div class="sec"><b>질문</b>${esc(t.question)}<div class="small muted">Seed ${esc(t.seed_id || "사례 검색")} · 연산자 ${esc(t.operator || "-")} (결정적 응답기 설정이라 문장은 Seed 그대로)</div></div>
      <div class="sec"><b>원 응답 → 공개 응답</b>${t.refused ? `<div class="small" style="margin-bottom:6px">공개 응답: ${esc(t.released)}</div>` : ""}<div class="cmp small">${cmp || '<span class="muted">사례 값 없음</span>'}</div></div>
      <div class="sec"><b>Defender 판정 (k = 그 값을 원래대로 넣었을 때)</b>${decHtml}</div></div>`;
  }).join("")}</div>`;
}
