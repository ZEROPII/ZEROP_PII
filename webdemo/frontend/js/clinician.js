// 의료진 화면: 공개된 답만 받는다 (GET /api/sessions/{id}/clinician)
import { api, esc, eul, h, kChip, kStatus, state, toast } from "./api.js";

const ui = { view: null, questions: [], group: "전체", seed: null, preview: null, focus: "사례1" };

export async function mount(root) {
  root.innerHTML = `
  <div class="grid3">
    <div class="stack">
      <section class="card">
        <div class="card-h"><h2>조회 시작</h2><span class="sub">POC와 같은 trial 번호</span></div>
        <div class="card-b">
          <label class="f" for="pt">지금 진료 중인 환자</label>
          <select id="pt" class="in"></select>
          <label class="f" for="prof">대상 AI 응답 수준</label>
          <select id="prof" class="in">
            <option value="staged">단계 공개형 — 처음엔 넓게, 더 물으면 기록대로</option>
            <option value="full">전면 공개형 — 처음부터 기록대로</option>
          </select>
          <button id="go" class="btn block">유사 사례 검색</button>
          <p class="hint">이 화면은 우리 도구가 지키는 의료 AI 서비스를 의료진 입장에서 흉내 낸 것입니다. 같은 대화를 보안 관제 화면에서 세 조건으로 나란히 볼 수 있습니다. T0014는 결과 보고 슬라이드 18의 대화입니다.</p>
        </div>
      </section>
      <section class="card">
        <div class="card-h"><h2>현재 환자 맥락</h2><span class="sub">검색 사례 아님</span></div>
        <div class="card-b" id="panel"><div class="empty">환자를 고르고 검색하세요.</div></div>
      </section>
      <section class="card">
        <div class="card-h"><h2>검색된 사례</h2><span class="sub">유사도 순 · 대화 내내 고정</span></div>
        <ul class="cases" id="cases"><li class="muted small" style="cursor:default">아직 검색하지 않았습니다.</li></ul>
      </section>
    </div>
    <section class="card chat">
      <div class="card-h"><h2>대화</h2><span class="sub" id="chatSub"></span></div>
      <div class="msgs" id="msgs"><div class="empty">유사 사례 검색을 누르면 대화가 시작됩니다.</div></div>
      <div class="composer hidden" id="composer"></div>
    </section>
    <div class="stack">
      <section class="card">
        <div class="card-h"><h2>재식별 위험</h2><span class="sub">사례별 후보 수 k</span></div>
        <div class="risk" id="risk"><div class="empty">검색 뒤에 표시됩니다.</div></div>
      </section>
      <section class="card">
        <div class="card-h"><h2>공개 내역</h2><span class="sub">이 대화 · 공개된 답 기준</span></div>
        <div id="disc"><div class="empty">검색 뒤에 표시됩니다.</div></div>
      </section>
    </div>
  </div>`;
  fillPatients(root.querySelector("#pt"));
  root.querySelector("#go").addEventListener("click", start);
  if (state.sessionId) await refresh(true);
}

function fillPatients(sel) {
  const groups = {};
  for (const p of state.patients) (groups[p.qtype_label] ||= []).push(p);
  sel.innerHTML = Object.entries(groups).map(([g, ps]) => `<optgroup label="${esc(g)} 조회">${ps.map((p) =>
    `<option value="${p.trial_id}">${p.trial_id} · ${esc(p.panel[0].value)} · ${esc(p.panel[1].value)}</option>`).join("")}</optgroup>`).join("");
  sel.value = "T0014";
}

async function start() {
  const trial_id = document.getElementById("pt").value;
  const profile = document.getElementById("prof").value;
  try {
    const { id } = await api("/api/sessions", { method: "POST", body: { trial_id, profile, fuzzer: "uniform" } });
    state.setSession(id);
    ui.seed = ui.preview = null; ui.group = "전체"; ui.focus = "사례1";
    await refresh(true);
  } catch (e) { toast(e.message); }
}

export async function refresh(withQuestions = true) {
  if (!state.sessionId) return;
  try {
    ui.view = await api(`/api/sessions/${state.sessionId}/clinician?arm=${state.arm}`, { quiet: true });
    if (withQuestions) ui.questions = await api(`/api/sessions/${state.sessionId}/questions?arm=${state.arm}`, { quiet: true });
  } catch (e) {
    if (e.status === 404) { state.setSession(null); toast("서버가 다시 시작되어 이전 대화가 없습니다. 새로 검색하세요."); return; }
    toast(e.message); return;
  }
  render();
}

function render() {
  const v = ui.view;
  if (!v || !document.getElementById("msgs")) return;       // 다른 화면으로 옮긴 뒤 늦게 온 응답
  const sel = document.getElementById("pt");
  if (sel && sel.value !== v.trial_id) sel.value = v.trial_id;
  const prof = document.getElementById("prof");
  if (prof) prof.value = v.profile;
  document.getElementById("panel").innerHTML = `<dl class="kv">${v.panel.map((p) => `<dt>${esc(p.label)}</dt><dd>${esc(p.value)}</dd>`).join("")}</dl>
    <p class="hint">질의 ${esc(v.trial_id)} · 환자 ${esc(v.patient)} · ${esc(v.profile_label)}</p>`;
  renderCases(v);
  renderChat(v);
  renderComposer(v);
  renderRisk(v);
  renderDisc(v);
}

function renderCases(v) {
  const ul = document.getElementById("cases");
  ul.innerHTML = v.cases.map((c) => `<li data-ref="${c.ref}" class="${c.ref === ui.focus ? "on" : ""}">
      <span class="case-no">${c.rank}</span>
      <span class="case-t"><b title="${esc(c.title)}">${esc((c.title || "(공개된 진단 없음)").split(" · ")[0])}</b><span>${esc(c.ref)} · 유사도 ${c.score}${c.title.includes(" · ") ? ` · ${esc(c.title.split(" · ")[1])}` : ""}</span></span>
      ${kChip(c.k, v.k_req)}</li>`).join("");
  ul.querySelectorAll("li[data-ref]").forEach((li) => li.addEventListener("click", () => { ui.focus = li.dataset.ref; renderCases(v); renderDisc(v); renderRisk(v); }));
}

// ── 대화 ──
function changeSentence(n) {
  const gen = n.changes.filter((c) => c.change === "generalize").map((c) => c.attribute);
  const sup = n.changes.filter((c) => c.change === "suppress").map((c) => c.attribute);
  const uniq = (a) => [...new Set(a)];
  const parts = [];
  if (gen.length) parts.push(`${eul(uniq(gen).join("·"))} 넓${sup.length ? "히고" : "혔습니다."}`);
  if (sup.length) parts.push(`${eul(uniq(sup).join("·"))} 뺐습니다.`);
  let why = "";
  if (n.k_if_raw != null) {
    why = n.k_if_raw < state.meta.k_req
      ? ` 그대로 답하면 ${n.case}의 후보가 ${n.k_if_raw}명이 됩니다.`
      : ` 그대로 답해도 ${n.case}의 후보는 ${n.k_if_raw}명이지만, 보호 기준(k > ${state.meta.generalize_threshold})을 지키려고 고쳤습니다.`;
  }
  return `${esc(n.case)}: ${esc(parts.join(" "))}${esc(why)}`;
}

function answerHtml(t) {
  if (t.refused) {
    return `<p class="refused">${esc(t.lines.map((l) => l.text || "").join(" "))}</p>
      <div class="change-note"><span class="i">i</span><span>답을 고쳐도 기준을 지킬 수 없어 보호 모드가 답 전체를 막았습니다.</span></div>`;
  }
  let html = "";
  const byCase = new Map();
  for (const l of t.lines) {
    if (!l.case) { html += `<p class="intro">${esc(l.text)}</p>`; continue; }
    if (!byCase.has(l.case)) byCase.set(l.case, []);
    byCase.get(l.case).push(l);
  }
  for (const [ref, ls] of byCase) {
    html += `<div class="ans-case"><h4>${esc(ref)}</h4>${ls.map((l) => {
      const m = l.field.match(/^\[(기록\d+)\]\s*(.*)$/);
      const fld = m ? `<span class="tag">${m[1]}</span> ${esc(m[2])}` : esc(l.field);
      const cls = l.change === "generalize" ? "gen" : l.change === "suppress" ? "sup" : "";
      const val = l.change === "suppress" ? "비공개" : esc(l.value);
      return `<div class="ans-line"><span class="fld">${fld}</span><span class="val ${cls}">${val}</span></div>`;
    }).join("")}</div>`;
  }
  if (t.change_notes.length) {
    html += `<div class="change-note"><span class="i">i</span><span>${t.change_notes.map(changeSentence).join("<br>")}</span></div>`;
  }
  return html || `<p class="muted">답할 내용이 없습니다.</p>`;
}

function renderChat(v) {
  document.getElementById("chatSub").textContent = `${v.arm_label} · 질문 ${v.turn}/${v.budget}`;
  const items = [...v.turns.map((t) => ({ turn: t.turn, t })), ...v.skipped.map((s) => ({ turn: s.turn, s }))].sort((a, b) => a.turn - b.turn);
  const msgs = document.getElementById("msgs");
  msgs.innerHTML = items.map(({ t, s }) => {
    if (s) return `<div class="sysmsg">턴 ${s.turn}: 이 보호 모드에서는 질문을 건너뛰었습니다 — ${esc(s.note || "")}</div>`;
    const who = t.turn === 0 ? "사례 검색" : t.picked_by && t.picked_by.startsWith("fuzzer") ? "퍼저가 고른 질문" : "의료진 질문";
    return `<div class="q"><div class="bubble">${esc(t.question)}</div><div class="meta">턴 ${t.turn} · ${who}</div></div>
      <div class="a"><span class="av">AI</span><div class="body">${answerHtml(t)}</div></div>`;
  }).join("");
  msgs.scrollTop = msgs.scrollHeight;
}

// ── 질문 고르기와 보내기 전 확인 ──
function renderComposer(v) {
  const box = document.getElementById("composer");
  box.classList.remove("hidden");
  const left = v.budget - v.turn;
  if (left <= 0 || !ui.questions.length) {
    box.innerHTML = `<div class="note">${left <= 0 ? `질문 예산 ${v.budget}턴을 다 썼습니다.` : "이 공개 상태에서 더 물을 수 있는 등록 질문이 없습니다."} 보안 관제 화면에서 세 조건의 결과를 비교해 보세요.</div>`;
    return;
  }
  const groups = { 전체: ui.questions.length };
  for (const q of ui.questions) groups[q.target_label] = (groups[q.target_label] || 0) + 1;
  if (!(ui.group in groups)) ui.group = "전체";
  const list = ui.questions.filter((q) => ui.group === "전체" || q.target_label === ui.group);
  const sel = ui.questions.find((q) => q.seed_id === ui.seed);
  box.innerHTML = `
    <div class="picker-h"><b>다음 질문 고르기</b><span class="budget">남은 질문 ${left}/${v.budget} · 등록 질문(Seed v0.13)만 답할 수 있는 응답기입니다</span></div>
    <div class="groups">${Object.entries(groups).map(([g, n]) => `<button data-g="${esc(g)}" class="${g === ui.group ? "on" : ""}">${esc(g)}<span>${n}</span></button>`).join("")}</div>
    <div class="qlist">${list.map((q) => `<button class="qitem ${q.seed_id === ui.seed ? "on" : ""}" data-s="${q.seed_id}">
        <span class="qt">${esc(q.text)}</span><span class="tg"><span class="tag">${esc(q.objective)}</span><span class="tag">${esc(q.scope)}</span></span></button>`).join("")}</div>
    <div id="warn"></div>
    <div class="send"><div class="box ${sel ? "" : "ph"}">${sel ? esc(ui.preview?.question || sel.text) : "위 목록에서 질문을 고르세요"}</div>
      <button class="btn" id="send" ${sel ? "" : "disabled"}>보내기</button></div>`;
  box.querySelectorAll(".groups button").forEach((b) => b.addEventListener("click", () => { ui.group = b.dataset.g; renderComposer(v); }));
  box.querySelectorAll(".qitem").forEach((b) => b.addEventListener("click", () => pick(b.dataset.s)));
  box.querySelector("#send")?.addEventListener("click", send);
  renderWarn();
}

async function pick(seedId) {
  ui.seed = seedId; ui.preview = null;
  renderComposer(ui.view);
  try {
    ui.preview = await api(`/api/sessions/${state.sessionId}/preview`, { method: "POST", body: { seed_id: seedId, arm: state.arm }, quiet: true });
  } catch (e) { toast(e.message); return; }
  if (ui.seed === seedId) renderComposer(ui.view);
}

function renderWarn() {
  const el = document.getElementById("warn");
  const p = ui.preview;
  if (!el || !p || p.seed_id !== ui.seed) { if (el) el.innerHTML = ""; return; }
  if (!p.applicable) { el.innerHTML = `<div class="warnbox"><span class="ic">!</span><div>${esc(p.note)}</div></div>`; return; }
  const worst = [...p.cases].sort((a, b) => a.k_if_raw - b.k_if_raw)[0];
  const gate = p.cases.filter((c) => c.defender && (c.defender.generalize || c.defender.suppress));
  const gateTxt = state.arm === "C0" ? "지금은 보호가 꺼져 있어 기록 그대로 나갑니다."
    : gate.length ? `보호 모드가 ${gate.map((c) => c.ref).join("·")}의 값을 넓히거나 뺄 것입니다.` : "보호 모드는 이 답을 그대로 내보낼 것입니다.";
  const alts = p.alternatives.length ? `<div class="alts">${p.alternatives.map((a) => `<button data-s="${a.seed_id}">${esc(a.target_label)}: ${esc(a.text.length > 28 ? a.text.slice(0, 28) + "…" : a.text)}</button>`).join("")}</div>` : "";
  if (p.warn) {
    const hits = p.cases.filter((c) => c.below);
    el.innerHTML = `<div class="warnbox"><span class="ic">!</span><div><b>보내기 전에 확인하세요.</b> 이 질문에 AI가 기록대로 답하면
      ${hits.map((c) => `${esc(c.ref)}의 후보가 ${c.k_now}명에서 <b>${c.k_if_raw}명</b>으로`).join(", ")} 줄어듭니다. ${esc(gateTxt)}${alts}</div></div>`;
  } else {
    el.innerHTML = `<div class="warnbox safe"><span class="ic">✓</span><div>기록대로 답해도 후보가 기준(${state.meta.k_req}명) 아래로 줄지 않습니다.
      가장 작은 후보 수는 ${esc(worst?.ref || "")} ${worst?.k_if_raw ?? "–"}명입니다. ${esc(gateTxt)}</div></div>`;
  }
  el.querySelectorAll(".alts button").forEach((b) => b.addEventListener("click", () => pick(b.dataset.s)));
}

async function send() {
  if (!ui.seed) return;
  try {
    await api(`/api/sessions/${state.sessionId}/turns`, { method: "POST", body: { seed_id: ui.seed, arm: state.arm } });
    ui.seed = ui.preview = null;
    await refresh(true);
  } catch (e) { toast(e.message); }
}

// ── 오른쪽 패널 ──
function renderRisk(v) {
  const max = Math.log(v.p_ref), mark = (Math.log(v.k_req) / max) * 100;
  const fillColor = { bad: "var(--bad)", warn: "#E39B2D", ok: "var(--blue-2)", gray: "#AAB4C3" };
  document.getElementById("risk").innerHTML = v.cases.map((c) => {
    const s = kStatus(c.k, v.k_req);
    const w = c.k > 0 ? Math.max(2, (Math.log(Math.max(c.k, 1)) / max) * 100) : 0;
    return `<div class="risk-row" data-ref="${c.ref}">
      <div class="top"><span>${esc(c.ref)}</span>${kChip(c.k, v.k_req)}</div>
      <div class="track"><div class="fill" style="width:${w}%;background:${fillColor[s.cls]}"></div><div class="mark" style="left:${mark}%"></div></div>
      <div class="bot"><span>공개 단서 ${c.n_disclosed}개</span><span>${s.cls === "bad" ? `기준 ${v.k_req}명 미만` : s.cls === "warn" ? "새 단서는 넓히거나 뺄 수 있음" : ""}</span></div></div>`;
  }).join("") + `<div class="legend-line"><span><i></i>기준 k = ${v.k_req}</span><span>막대: 로그 눈금 (최대 ${v.p_ref}명)</span></div>`;
  document.querySelectorAll("#risk .risk-row").forEach((r) => r.addEventListener("click", () => { ui.focus = r.dataset.ref; renderCases(v); renderDisc(v); }));
}

function renderDisc(v) {
  const c = v.cases.find((x) => x.ref === ui.focus) || v.cases[0];
  const badge = { null: '<span class="chip info">그대로</span>', generalize: '<span class="chip c1">넓힘</span>', suppress: '<span class="chip gray">비공개</span>' };
  document.getElementById("disc").innerHTML = `
    <div class="tabs">${v.cases.map((x) => `<button data-ref="${x.ref}" class="${x.ref === c.ref ? "on" : ""}">${esc(x.ref)}</button>`).join("")}</div>
    <ul class="dlist">${c.disclosures.length ? c.disclosures.map((d) => `<li><span class="t">턴 ${d.turn}</span>
        <span class="v">${esc(d.field.replace(/^\[기록\d+\]\s*/, ""))}${d.change === "suppress" ? "" : `<br><b>${esc(d.value)}</b>`}</span>
        ${badge[d.change ?? "null"]}</li>`).join("") : '<li class="muted small" style="display:block">아직 공개된 단서가 없습니다.</li>'}</ul>`;
  document.querySelectorAll("#disc .tabs button").forEach((b) => b.addEventListener("click", () => { ui.focus = b.dataset.ref; renderCases(v); renderDisc(v); }));
}
