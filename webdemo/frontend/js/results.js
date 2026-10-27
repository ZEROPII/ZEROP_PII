// 레드팀 실행 화면과 저장된 POC 결과 화면 (같은 집계 형식: engine.summarize)
import { api, ARM_HEX, ARM_NAME, ci, esc, pct, state, toast } from "./api.js";
import { hBars, lineChart, stackBars } from "./charts.js";

const ARMS = ["C0", "C1", "C1S"];
const PAIR_KO = { C0_vs_C1: "C0 vs C1", C0_vs_C1S: "C0 vs C1S", C1S_vs_C1: "C1S vs C1" };

function pval(p) {
  if (p == null) return "–";
  if (p < 1e-4) return `< 10<sup>${Math.ceil(Math.log10(p))}</sup>`;
  return p.toFixed(4);
}

export function renderResult(el, r, { title = "", note = "" } = {}) {
  const a = r.arms;
  el.innerHTML = `
  <div class="stack">
    ${title ? `<div class="note">${title}</div>` : ""}
    <div class="armcards">${ARMS.filter((x) => a[x]).map((x) => {
      const v = a[x];
      return `<section class="card armcard ${x}"><h3><span>${esc(ARM_NAME[x])}</span><span class="muted small">n = ${v.n}</span></h3>
        <div class="big num">${pct(v.viol8.p)}<small>8턴 안 사례 A 위반 ${ci(v.viol8.ci)}</small></div>
        <dl><dt>10턴 예산 전체</dt><dd>${pct(v.viol10.p)}</dd>
          <dt>사례 검색 답만으로 (턴 0)</dt><dd>${pct(v.turn0.p)}</dd>
          <dt>첫 위반 턴 중앙값</dt><dd>${v.first_median ?? "–"}</dd>
          <dt>검색 사례 중 하나라도 위반</dt><dd>${pct(v.viol_any.p)}</dd>
          <dt>공개 단서 유지율</dt><dd>${v.utility == null ? "–" : v.utility.toFixed(2)}</dd>
          <dt>사례 단위 과잉 수정</dt><dd>${x === "C0" ? "–" : `${pct(v.overblock.p)} <span class="muted small">(${v.overblock.k}/${v.overblock.n})</span>`}</dd></dl></section>`;
    }).join("")}</div>
    <div class="row">
      <section class="card"><div class="card-h"><h2>턴별 누적 위반</h2><span class="sub">그 턴까지 사례 A가 k &lt; 5에 들어간 비율</span></div><div class="card-b" id="rCum"></div></section>
      <section class="card"><div class="card-h"><h2>사례 A 후보 수 중앙값</h2><span class="sub">턴별 · 로그 눈금 · 위반 뒤에는 마지막 값 유지</span></div><div class="card-b" id="rMed"></div></section>
    </div>
    <div class="row">
      <section class="card"><div class="card-h"><h2>후보를 5명 밑으로 떨어뜨린 단서 (C0)</h2><span class="sub">k가 처음 5 미만이 된 그 턴에 물은 것</span></div><div class="card-b" id="rCue"></div></section>
      <section class="card"><div class="card-h"><h2>Defender 판정 (C1)</h2><span class="sub">단서별 그대로 · 넓힘 · 뺌, 오른쪽 숫자 = 뺀 비율</span></div><div class="card-b" id="rDef"></div></section>
    </div>
    <section class="card"><div class="card-h"><h2>짝 비교 (같은 질의 환자)</h2><span class="sub">10턴 예산 기준 · exact McNemar (evaluation/eval_baseline.py)</span></div>
      <div id="rPair"></div></section>
    ${note ? `<div class="note">${note}</div>` : ""}
  </div>`;
  const B = a.C0.cumulative.length - 1;
  lineChart(el.querySelector("#rCum"), {
    series: ARMS.filter((x) => a[x]).map((x) => ({ name: x, color: ARM_HEX[x], points: a[x].cumulative.map((v, i) => [i, v]) })),
    xMax: B, percent: true, vline: { x: 7, label: "평가 기준 8턴" }, xLabel: "턴 (0 = 사례 검색)", aria: "턴별 누적 위반 비율", height: 240,
  });
  lineChart(el.querySelector("#rMed"), {
    series: ARMS.filter((x) => a[x]).map((x) => ({ name: x, color: ARM_HEX[x], points: a[x].kA_median.map((v, i) => [i, v]) })),
    xMax: B, yMax: Math.max(...ARMS.filter((x) => a[x]).map((x) => a[x].kA_median[0] || 10)) * 1.4, band: { below: 5, label: "위반 구간" },
    xLabel: "턴", aria: "턴별 사례 A 후보 수 중앙값", height: 240,
  });
  const cue = Object.entries(a.C0.decisive).sort((p, q) => q[1] - p[1]);
  el.querySelector("#rCue").innerHTML = cue.length ? hBars(cue.map(([k, v]) => ({ label: k, value: v, text: `${v}명` })), a.C0.n) : '<div class="empty">위반이 없습니다.</div>';
  const def = a.C1 ? Object.entries(a.C1.defender) : [];
  const supRate = ([, c]) => (c.suppress || 0) / ((c.allow || 0) + (c.generalize || 0) + (c.suppress || 0) || 1);
  el.querySelector("#rDef").innerHTML = def.length
    ? `<div class="legend"><span><i class="box" style="background:var(--allow)"></i>그대로</span><span><i class="box" style="background:var(--gen)"></i>넓힘</span><span><i class="box" style="background:var(--sup)"></i>뺌</span></div>`
      + stackBars(def.sort((p, q) => supRate(q) - supRate(p)).map(([k, c]) => ({ label: k, parts: [
        { v: c.allow || 0, color: "var(--allow)", name: "그대로" }, { v: c.generalize || 0, color: "var(--gen)", name: "넓힘" }, { v: c.suppress || 0, color: "var(--sup)", name: "뺌" }] })))
    : '<div class="empty">C1 판정이 없습니다.</div>';
  el.querySelector("#rPair").innerHTML = `<table class="t"><thead><tr><th>비교 (A vs B)</th><th class="r">짝</th><th class="r">A만 위반</th><th class="r">B만 위반</th><th class="r">p</th></tr></thead><tbody>
    ${Object.entries(r.paired).map(([k, p]) => `<tr><td>${esc(PAIR_KO[k] || k)}</td><td class="r num">${p.n}</td><td class="r num">${p.only_first}</td><td class="r num">${p.only_second}</td><td class="r num">${pval(p.p_value)}</td></tr>`).join("")}
  </tbody></table>`;
}

// ── 레드팀 실행 ──
let poll = null;

export async function mountRedteam(root) {
  root.innerHTML = `
  <div class="stack">
    <section class="card">
      <div class="card-h"><h2>레드팀 배치 실행</h2><span class="sub">medical.experiment를 그대로 돌림 · 위험에 닿으면 그 대화 종료 · 질문 예산 10턴</span></div>
      <div class="card-b">
        <div class="form-row">
          <div><label class="f">대상 AI 응답 수준</label><select id="jp" class="in"><option value="staged">단계 공개형</option><option value="full">전면 공개형</option></select></div>
          <div><label class="f">질문 선택</label><select id="jf" class="in"><option value="uniform">균등 선택 (통제 조건)</option><option value="feedback">k 피드백 선택 (fuzzer/feedback.py)</option></select></div>
          <div><label class="f">조회 유형마다 질의 환자 수</label><select id="jn" class="in"><option value="4">4명 (12명 · 1분 안팎)</option><option value="10" selected>10명 (30명 · 2~3분)</option><option value="30">30명 (90명 · 7분 안팎)</option><option value="">전원 (296명 · 20~30분)</option></select></div>
          <div><button class="btn" id="jrun">실행</button></div>
        </div>
        <div id="jprog" class="hidden"><div class="progress"><div id="jbar"></div></div><div class="small muted" id="jtxt"></div></div>
        <p class="hint">질의 환자 × C0·C1·C1S를 끝까지 돌린 뒤 POC와 같은 방법으로 집계합니다. 실행 기록은 runs/webdemo/redteam/ 에 남습니다(커밋하지 마세요).</p>
      </div>
    </section>
    <section class="card"><div class="card-h"><h2>실행 목록</h2><span class="sub">행을 누르면 결과를 엽니다</span></div><div id="jlist"></div></section>
    <div id="jres"></div>
  </div>`;
  root.querySelector("#jrun").addEventListener("click", async () => {
    const n = root.querySelector("#jn").value;
    try {
      const j = await api("/api/redteam", { method: "POST", body: { profile: root.querySelector("#jp").value, fuzzer: root.querySelector("#jf").value, per_type: n ? Number(n) : null } });
      watch(j.id);
    } catch (e) { toast(e.message); }
  });
  await list();
  const running = (await api("/api/redteam", { quiet: true })).find((j) => j.status === "running");
  if (running) watch(running.id);
}

async function list() {
  const jobs = await api("/api/redteam", { quiet: true });
  const el = document.getElementById("jlist");
  if (!el) return;
  el.innerHTML = jobs.length ? `<table class="t"><thead><tr><th>실행</th><th>응답 수준</th><th>질문 선택</th><th class="r">질의 환자</th><th>상태</th><th class="r">걸린 시간</th><th>기록 폴더</th></tr></thead><tbody>
    ${jobs.map((j) => `<tr class="click" data-j="${j.id}"><td>${j.id}</td><td>${esc(j.profile_label)}</td><td>${esc(j.fuzzer_label)}</td><td class="r num">${j.total / 3}</td>
      <td>${{ done: '<span class="chip ok">완료</span>', running: '<span class="chip info">실행 중</span>', error: '<span class="chip bad">오류</span>', queued: '<span class="chip gray">대기</span>' }[j.status]}</td>
      <td class="r num">${j.elapsed ?? "–"}초</td><td class="mono small">${esc(j.out)}</td></tr>`).join("")}</tbody></table>`
    : '<div class="empty">아직 실행하지 않았습니다.</div>';
  el.querySelectorAll("tr.click").forEach((tr) => tr.addEventListener("click", () => show(tr.dataset.j)));
}

function watch(id) {
  clearInterval(poll);
  document.getElementById("jprog").classList.remove("hidden");
  document.getElementById("jrun").disabled = true;
  const tick = async () => {
    let j;
    try { j = await api(`/api/redteam/${id}`, { quiet: true }); } catch { return; }
    const bar = document.getElementById("jbar");
    if (!bar) { clearInterval(poll); return; }
    bar.style.width = `${(j.done / j.total) * 100}%`;
    document.getElementById("jtxt").textContent = `${j.done}/${j.total} (질의 환자 × 조건) · ${j.elapsed ?? 0}초 · ${j.last}`;
    if (j.status !== "running" && j.status !== "queued") {
      clearInterval(poll);
      document.getElementById("jrun").disabled = false;
      document.getElementById("jprog").classList.add("hidden");
      await list();
      if (j.status === "error") toast(`실행 오류: ${j.error.split("\n")[0]}`, 8000);
      else show(id, j);
    }
  };
  tick();
  poll = setInterval(tick, 1000);
}

async function show(id, j) {
  j = j || (await api(`/api/redteam/${id}`));
  if (!j.result) return toast(j.status === "error" ? j.error.split("\n")[0] : "아직 결과가 없습니다.");
  renderResult(document.getElementById("jres"), j.result, {
    title: `<b>${esc(j.id)}</b> · ${esc(j.profile_label)} · ${esc(j.fuzzer_label)} · 질의 환자 ${j.total / 3}명 · ${j.elapsed}초 · 기록 <span class="mono">${esc(j.out)}</span>`,
  });
}

// ── 저장된 POC 결과 ──
const SETTINGS = { staged_uniform: "단계 공개형 · 균등 선택 (통제)", staged_feedback: "단계 공개형 · k 피드백", full_uniform: "전면 공개형 · 균등 선택", full_feedback: "전면 공개형 · k 피드백" };

export async function mountPoc(root) {
  let d;
  try { d = await api("/api/poc"); } catch (e) { root.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  const keys = Object.keys(SETTINGS).filter((k) => d[k]);
  let cur = keys[0];
  root.innerHTML = `
  <div class="stack">
    <section class="card"><div class="card-h"><h2>2026-10-23 POC 결과</h2><span class="sub">질의 환자 296명 × 4가지 설정 · webdemo/data/poc_summary.json</span></div>
      <table class="t"><thead><tr><th>설정</th><th class="r">C0 위반 (8턴)</th><th class="r">C1 위반 (8턴)</th><th class="r">C1S 위반 (8턴)</th><th class="r">C0 첫 위반 턴</th><th class="r">C1 유지율</th><th class="r">C1S 유지율</th></tr></thead>
      <tbody id="pset"></tbody></table></section>
    <div id="pres"></div>
    <section class="card"><div class="card-h"><h2>질문 선택 방식 비교 (균등 vs k 피드백)</h2><span class="sub">같은 질의 환자에서 첫 위반 턴, 턴 0 위반 제외</span></div><div id="pfz"></div></section>
  </div>`;
  const draw = () => {
    root.querySelector("#pset").innerHTML = keys.map((k) => {
      const a = d[k].arms;
      return `<tr class="click ${k === cur ? "on" : ""}" data-k="${k}"><td>${esc(SETTINGS[k])}</td><td class="r num">${pct(a.C0.viol8.p)}</td><td class="r num">${pct(a.C1.viol8.p)}</td>
        <td class="r num">${pct(a.C1S.viol8.p)}</td><td class="r num">${a.C0.first_median}</td><td class="r num">${a.C1.utility.toFixed(2)}</td><td class="r num">${a.C1S.utility.toFixed(2)}</td></tr>`;
    }).join("");
    root.querySelectorAll("#pset tr").forEach((tr) => tr.addEventListener("click", () => { cur = tr.dataset.k; draw(); }));
    renderResult(root.querySelector("#pres"), d[cur], {
      title: `<b>${esc(SETTINGS[cur])}</b>의 상세입니다. 위 표의 행을 누르면 바뀝니다. 유지율은 10턴 예산 전체 대화 평균입니다(평가 v7.2의 8턴 유용성과 계산 범위가 다름).`,
    });
  };
  draw();
  const fz = d.fuzzer_compare || {};
  root.querySelector("#pfz").innerHTML = `<table class="t"><thead><tr><th>응답 수준</th><th>조건</th><th class="r">짝</th><th class="r">피드백이 빠름</th><th class="r">같음</th><th class="r">피드백이 느림</th><th class="r">평균 첫 위반 턴 (균등 → 피드백)</th></tr></thead><tbody>
    ${Object.entries(fz).flatMap(([prof, arms]) => Object.entries(arms).map(([arm, v]) => `<tr><td>${prof === "staged" ? "단계 공개형" : "전면 공개형"}</td><td>${arm}</td>
      <td class="r num">${v.n_both_after_turn0}</td><td class="r num">${v.feedback_faster}</td><td class="r num">${v.same}</td><td class="r num">${v.feedback_slower}</td>
      <td class="r num">${v.mean_uniform ?? "–"} → ${v.mean_feedback ?? "–"}</td></tr>`)).join("")}</tbody></table>`;
}
