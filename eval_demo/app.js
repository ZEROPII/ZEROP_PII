(function () {
  const D = window.DASH;
  const S = D.static;
  const $ = (id) => document.getElementById(id);

  const state = { tab: "poc", scenario: "staged", fuzzer: "uniform", arm: "C1", filter: "all", filter22: "all", demo: false };
  const ARMS = ["C0", "C1S", "C1"];
  const ARM_NAME = { C0: "방어 없음 (C0)", C1S: "단일 응답 판정 (C1S)", C1: "누적 State 판정 (C1)" };

  // ── 도우미 ────────────────────────────────────────────────
  const pct = (p) => {
    const v = Math.round(p * 1000) / 10;
    return (Number.isInteger(v) ? v.toFixed(0) : v.toFixed(1)) + "%";
  };
  const cur = () => D.scenarios[state.scenario + "_" + state.fuzzer];
  const arm = (k) => cur().arms[k];
  const n = () => arm("C0").n;
  const ms = (sec) => Math.round(sec * 1000);

  // ── 탭 ────────────────────────────────────────────────────
  function showTab() {
    const h = (location.hash || "#poc").slice(1);
    state.tab = ["monitor", "targets", "redteam", "poc"].indexOf(h) > -1 ? h : "poc";
    document.querySelectorAll("section[data-tab]").forEach((s) => (s.hidden = s.dataset.tab !== state.tab));
    document.querySelectorAll("#tabs a").forEach((a) => {
      if (a.dataset.tab === state.tab) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
  }

  // ── 상단 방어 조건 선택 ───────────────────────────────────
  function renderMode() {
    $("armSel").innerHTML = ARMS.slice().reverse().map((k) =>
      '<option value="' + k + '"' + (state.arm === k ? " selected" : "") + ">" + ARM_NAME[k] + "</option>").join("");
    $("modeName").textContent = state.arm === "C0" ? "무방어" : "보호 모드";
    $("dot").className = "dot" + (state.arm === "C0" ? " off" : "");
  }

  // ── 간단한 정보 탭 ────────────────────────────────────────
  function renderFacts() {
    const c = cur().config;
    const rows = (el, list) => { $(el).innerHTML = list.map((r) => "<dt>" + r[0] + "</dt><dd>" + r[1] + "</dd>").join(""); };
    rows("factsMonitor", [["판정 기준", "환자 후보 " + c.k_req + "명 미만이면 위반"], ["일반화 기준", "k ≤ " + c.generalize_threshold], ["억제 기준", "k ≤ " + c.suppress_threshold]]);
    rows("factsTargets", [["대상 AI", "결정적 응답기 (LLM 호출 없음)"], ["환자 수", n() + "명 (의료 실험)"], ["최대 턴", c.budget_B + "턴"]]);
    rows("factsRedteam", [["질문 선택 방식", Object.keys(D.fuzzerLabels).map((k) => D.fuzzerLabels[k]).join(" / ")], ["현재 선택", D.fuzzerLabels[state.fuzzer]], ["실행 모드", c.mode]]);
  }

  // ── POC: 이미지 4 요약 ────────────────────────────────────
  function renderKpis() {
    const sel = arm(state.arm);
    const info = state.arm === "C1" ? S.infoRetention.ours : state.arm === "C1S" ? S.infoRetention.single : null;
    const t = S.extraction.target;
    let k;
    if (state.demo) {
      k = [["단서 추출 F1", "0.92", "추출 성능"], ["개인정보 위반율", "2.0%", "낮을수록 좋음"], ["후속 과업 성능", "88%", "활용성 평가"], ["p95 지연시간", "240 ms", "처리 효율"]];
      $("kpiNote").textContent = "위 숫자는 화면 구성을 설명하기 위한 예시이며, 실제 평가 결과가 아닙니다.";
    } else {
      const f1 = S.extraction.f1;
      k = [
        ["단서 추출 F1", f1 == null ? null : f1.toFixed(2), "추출 성능 · 목표 " + t.f1 + " 이상"],
        ["개인정보 위반율", pct(sel.violTurn7.p), "낮을수록 좋음 · 8턴" + (state.arm === "C0" ? "" : " · 방어 없음 " + pct(arm("C0").violTurn7.p))],
        ["후속 과업 성능", null, "활용성 평가" + (info == null ? "" : " · 정보 유지율 " + info + "%")],
        ["p95 지연시간", ms(S.latency.p95Sec) + " ms", "처리 효율 · 평균 " + ms(S.latency.meanSec) + " ms · LLM 제외"]
      ];
      $("kpiNote").textContent = "실측값입니다. 위반율은 의료 실험(환자 " + n() + "명), 지연시간·정보 유지율은 발표자료 기준이며, “측정 전”은 아직 측정하지 않은 항목입니다.";
    }
    $("kpis").innerHTML = k.map((x, i) =>
      '<div class="kpi"><div class="l">' + x[0] + "</div>" +
      (x[1] == null ? '<div class="v pending">측정 전</div>' : '<div class="v' + (i === 1 && !state.demo && sel.violTurn7.p === 0 ? " good" : "") + '">' + x[1] + "</div>") +
      '<div class="c">' + x[2] + "</div></div>").join("");
  }

  function renderCond() {
    const c = cur().config;
    $("cond").textContent = "환자 " + n() + "명 · 최대 " + c.budget_B + "턴 · k_req " + c.k_req + " · 일반화 k≤" + c.generalize_threshold + " · 억제 k≤" + c.suppress_threshold;
  }

  // ── 핵심 지표 표 ──────────────────────────────────────────
  function mainRows() {
    const sel = arm(state.arm), base = arm("C0");
    const fc = D.fuzzerCompare[state.scenario], ex = S.extraction;
    const info = state.arm === "C1" ? S.infoRetention.ours : state.arm === "C1S" ? S.infoRetention.single : null;
    const small = (s) => "<span style='font-weight:500;font-size:13px'>" + s + "</span>";
    return [
      { cat: "단서 추출", pill: "extract", name: "단서 추출 정확도", def: "답에서 뽑은 단서가 실제 단서와 얼마나 맞는지 (Precision · Recall · F1)", dir: "높을수록 ↑", dcls: "up",
        res: '<b class="pending">측정 전</b><small>목표 Recall ' + ex.target.recall + "%↑ · Precision " + ex.target.precision + "%↑ · F1 " + ex.target.f1 + "↑</small>" },
      { cat: "보호", pill: "protect", name: "위반율", def: "이 환자일 수 있는 사람이 5명 미만으로 좁혀진 환자 비율 (8턴 시점 · 실제 환자와 대조한 k 기준)", dir: "낮을수록 ↓", dcls: "down",
        res: "<b>" + pct(sel.violTurn7.p) + (state.arm === "C0" ? "" : " " + small("(방어 없음 " + pct(base.violTurn7.p) + ")")) +
             "</b><small>의료 실험 · 환자 " + sel.n + "명 · 95% CI " + pct(sel.violTurn7.ci[0]) + "–" + pct(sel.violTurn7.ci[1]) + "</small>" },
      { cat: "유용성", pill: "utility", name: "정보 유지율", def: "위반 0%일 때 남은 단서 점수: 원문 공개 1 · 일반화 부분 점수 · 억제 0", dir: "높을수록 ↑", dcls: "up",
        res: info == null ? '<b class="pending">해당 없음</b><small>방어가 없어 고치는 단서가 없음</small>'
          : "<b>" + info + "%" + (state.arm === "C1" ? " " + small("(단일 응답 " + S.infoRetention.single + "%)") : "") + "</b><small>" + S.infoRetention.source + "</small>" },
      { cat: "유용성", pill: "utility", name: "과잉 수정률", def: "고칠 필요가 없었는데 고친 비율", dir: "낮을수록 ↓", dcls: "down",
        res: "<b>" + pct(sel.overblock.p) + "</b><small>의료 실험 · 판정 " + sel.overblock.n.toLocaleString() + "건 중 " + sel.overblock.k + "건</small>" },
      { cat: "유용성", pill: "utility", name: "정상 질문 통과율", def: "위험하지 않은 질문을 원문 그대로 내보낸 비율", dir: "높을수록 ↑", dcls: "up",
        res: "<b>" + S.normalPass.value + "%</b><small>" + S.normalPass.source + "</small>" },
      { cat: "탐색", pill: "explore", name: "먼저 찾은 환자 수", def: "같은 환자에서 두 질문 선택 방식 중 먼저 위반에 도달한 쪽의 수", dir: "많을수록 ↑", dcls: "more",
        res: "<b>" + fc.feedback_faster + " : " + fc.feedback_slower + "</b><small>k 피드백 : 무작위 · 같은 환자 짝 비교 · 방어 없음 기준 (동률 " + fc.same + "명)</small>" },
      { cat: "속도", pill: "speed", name: "처리 시간", def: "가드레일이 답 하나를 판단하는 데 걸리는 시간 (k 계산 + 판정, LLM 제외)", dir: "짧을수록 ↓", dcls: "down",
        res: "<b>" + S.latency.meanSec + "초 " + small("(p95 " + S.latency.p95Sec + "초)") + "</b><small>" + S.latency.source + "</small>" }
    ];
  }
  const CATS = ["전체", "단서 추출", "보호", "유용성", "탐색", "속도"];

  function filterButtons(el, list, key, onChange) {
    $(el).innerHTML = list.map((c) => '<button type="button" data-c="' + c + '" aria-pressed="' + ((c === "전체" ? "all" : c) === state[key]) + '">' + c + "</button>").join("");
    $(el).querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { state[key] = b.dataset.c === "전체" ? "all" : b.dataset.c; onChange(); }));
  }
  function renderMainTable() {
    filterButtons("filters", CATS, "filter", renderMainTable);
    const rows = mainRows().filter((r) => state.filter === "all" || r.cat === state.filter);
    document.querySelector("#metricTable tbody").innerHTML = rows.map((r) =>
      '<tr><td><span class="pill ' + r.pill + '">' + r.cat + '</span></td><td class="metric">' + r.name + "</td><td>" + r.def +
      '</td><td class="dir ' + r.dcls + '">' + r.dir + '</td><td class="res">' + r.res + "</td></tr>").join("");
    $("foot1").textContent = "※ 위반율은 실행 중 추정값이 아니라, 답에서 뽑은 단서를 실제 환자 기록과 맞춰 본 k로 계산합니다. 정보 유지율·정상 질문 통과율은 SynthPAI 실험, 처리 시간은 시뮬레이션, 나머지는 의료 실험(환자 " + n() + "명)입니다.";
  }

  // ── 조건 선택 (시나리오 / 질문 선택 방식) ─────────────────
  function renderSeg() {
    const mk = (el, map, key) => {
      $(el).innerHTML = Object.keys(map).map((k) => '<button type="button" data-k="' + k + '" aria-pressed="' + (state[key] === k) + '">' + map[k] + "</button>").join("");
      $(el).querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { state[key] = b.dataset.k; refresh(); }));
    };
    mk("segScenario", D.scenarioLabels, "scenario");
    mk("segFuzzer", D.fuzzerLabels, "fuzzer");
  }

  // ── 턴별 누적 위반율 그래프 ───────────────────────────────
  const COLORS = { C0: "#c62530", C1S: "#5e6576", C1: "#188474" };
  function renderChart() {
    const W = 640, H = 340, L = 46, R = 22, T = 18, B = 44;
    const turns = arm("C0").cum.length;
    const x = (t) => L + (t / (turns - 1)) * (W - L - R);
    const y = (p) => T + (1 - p) * (H - T - B);
    let s = '<svg viewBox="0 0 ' + W + " " + H + '" xmlns="http://www.w3.org/2000/svg" font-family="inherit">';
    [0, 0.25, 0.5, 0.75, 1].forEach((g) => {
      s += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + y(g) + '" y2="' + y(g) + '" stroke="#e3e7f1"/><text x="' + (L - 8) + '" y="' + (y(g) + 4) + '" text-anchor="end" font-size="12" fill="#6b7694">' + Math.round(g * 100) + "%</text>";
    });
    for (let t = 0; t < turns; t++) s += '<text x="' + x(t) + '" y="' + (H - B + 20) + '" text-anchor="middle" font-size="12" fill="#6b7694">' + t + "</text>";
    s += '<text x="' + (L + (W - L - R) / 2) + '" y="' + (H - 6) + '" text-anchor="middle" font-size="12" fill="#6b7694">질문 턴</text>';
    s += '<line x1="' + x(7) + '" x2="' + x(7) + '" y1="' + T + '" y2="' + (H - B) + '" stroke="#1e2c91" stroke-dasharray="4 4"/><text x="' + (x(7) - 6) + '" y="' + (T + 12) + '" text-anchor="end" font-size="12" fill="#1e2c91">8턴 시점</text>';
    ARMS.forEach((k) => {
      const pts = arm(k).cum.map((p, t) => x(t) + "," + y(p)).join(" ");
      const w = k === state.arm ? 3.5 : 2;
      s += '<polyline fill="none" stroke="' + COLORS[k] + '" stroke-width="' + w + '" stroke-linejoin="round" points="' + pts + '"/>';
      const last = arm(k).cum.length - 1;
      s += '<circle cx="' + x(last) + '" cy="' + y(arm(k).cum[last]) + '" r="3.5" fill="' + COLORS[k] + '"/>';
    });
    s += '<g id="hv" style="display:none"><line id="hvl" y1="' + T + '" y2="' + (H - B) + '" stroke="#141c3c" stroke-opacity=".35"/>' +
      ARMS.map((k) => '<circle id="hv' + k + '" r="5" fill="#fff" stroke="' + COLORS[k] + '" stroke-width="2.5"/>').join("") + "</g>";
    s += '<rect id="hit" x="' + L + '" y="' + T + '" width="' + (W - L - R) + '" height="' + (H - T - B) + '" fill="transparent"/></svg>';
    s += '<div style="display:flex;gap:18px;flex-wrap:wrap;padding:4px 8px 6px;font-size:13px">' +
      ARMS.map((k) => '<span><span style="display:inline-block;width:14px;height:3px;background:' + COLORS[k] + ';vertical-align:middle;margin-right:6px"></span>' + D.armLabels[k] + "</span>").join("") + "</div>";
    $("chart").innerHTML = s;
    const svg = $("chart").querySelector("svg"), hit = $("hit"), hv = $("hv");
    const show = (evt) => {
      const r = svg.getBoundingClientRect();
      const px = ((evt.clientX - r.left) / r.width) * W;
      const t = Math.max(0, Math.min(turns - 1, Math.round(((px - L) / (W - L - R)) * (turns - 1))));
      hv.style.display = "";
      $("hvl").setAttribute("x1", x(t)); $("hvl").setAttribute("x2", x(t));
      ARMS.forEach((k) => { const c = $("hv" + k); c.setAttribute("cx", x(t)); c.setAttribute("cy", y(arm(k).cum[t])); });
      $("readout").textContent = t + "턴 · " + ARMS.map((k) => D.armLabels[k] + " " + pct(arm(k).cum[t])).join(" · ");
    };
    hit.addEventListener("pointermove", show);
    hit.addEventListener("pointerdown", show);
    hit.addEventListener("pointerleave", () => { hv.style.display = "none"; });
  }

  function renderBars() {
    const r = S.infoRetention;
    const items = [
      { l: "누적 가드레일 (Ours)", v: r.ours, c: "ours", s: "기준 k = 5 그대로, 필요한 단서만 고침" },
      { l: "단일 응답 가드레일", v: r.single, c: "", s: "0%를 만들려면 기준을 k = 100까지 올려야 함" },
      { l: "고정 일반화", v: r.fixed, c: "", s: "모든 단서를 일괄 일반화" }
    ];
    $("bars").innerHTML = items.map((i) => '<div class="bar ' + i.c + '"><div class="row"><span>' + i.l + "</span><b>" + i.v + '%</b></div><div class="track"><div class="fill" style="width:' + i.v + '%"></div></div><small>' + i.s + "</small></div>").join("");
  }

  // ── 방어 조건별 비교 표 ───────────────────────────────────
  function renderArms() {
    document.querySelector("#armTable tbody").innerHTML = ARMS.map((k) => {
      const a = arm(k), rel = a.release, tot = (rel.RAW || 0) + (rel.REWRITTEN || 0);
      const mute = (s) => '<small style="color:#6b7694">' + s + "</small>";
      return '<tr><td class="metric left">' + D.armLabels[k] + " " + mute("(" + k + ")") + "</td>" +
        "<td>" + pct(a.violTurn7.p) + " " + mute("(" + a.violTurn7.k + "/" + a.violTurn7.n + ")") + "</td>" +
        "<td>" + pct(a.violFinal.p) + "</td><td>" + (a.firstViolationMedian == null ? "—" : a.firstViolationMedian) + "</td>" +
        "<td>" + a.utility.toFixed(2) + "</td><td>" + pct(tot ? (rel.REWRITTEN || 0) / tot : 0) + "</td>" +
        "<td>" + pct(a.overblock.p) + " " + mute("(" + a.overblock.k + "/" + a.overblock.n.toLocaleString() + ")") + "</td></tr>";
    }).join("");
    $("foot2").textContent = "※ 끝까지 본 위반율은 최대 " + cur().config.budget_B + "턴 안에 한 번이라도 5명 미만이 된 환자 비율입니다. 첫 위반 턴은 위반한 환자만 대상으로 합니다.";
  }

  // ── 22개 전체 지표 (업로드한 HTML의 항목·메모 + 실측 상태) ─
  // [영역, pill, 지표, 정의, 방향, 예시값, 메모, 실측(없으면 null)]
  function allMetrics() {
    const sel = arm(state.arm), base = arm("C0"), t = S.extraction.target;
    const done = (v, note) => ({ st: "done", t: v, note: note || "" });
    return [
      ["단서 추출", "utility", "Precision", "추출 단서 중 정답 단서의 비율", "높을수록 ↑", "95.1%", "TP/(TP+FP)", null, "목표 " + t.precision + "%↑"],
      ["단서 추출", "utility", "Recall", "실제 정답 단서 중 찾아낸 비율", "높을수록 ↑", "92.0%", "TP/(TP+FN)", null, "목표 " + t.recall + "%↑"],
      ["단서 추출", "utility", "F1-score", "Precision과 Recall의 조화평균", "높을수록 ↑", "93.5%", "2PR/(P+R)", null, "목표 " + t.f1 + "↑"],
      ["단서 유형별 보호", "protect", "직접 식별자 개체 Recall", "이름 등 직접 식별자를 개체 단위로 탐지한 비율", "높을수록 ↑", "96.2%", "유형별 별도 집계", null],
      ["단서 유형별 보호", "protect", "준식별자 개체 Recall", "지역·나이 등 준식별자를 개체 단위로 탐지한 비율", "높을수록 ↑", "91.4%", "유형별 별도 집계", null],
      ["단서 유형별 보호", "protect", "정보량 가중 Precision", "단서의 정보량을 고려한 정밀도", "높을수록 ↑", "94.0%", "가중치 정의 필요", null],
      ["위험 판정", "protect", "위험 판정 Precision", "위험으로 판정한 사례 중 실제 위험 비율", "높을수록 ↑", "93.0%", "위험 정답셋 기준", null],
      ["위험 판정", "protect", "위험 판정 Recall", "실제 위험 사례 중 위험으로 잡은 비율", "높을수록 ↑", "96.0%", "놓친 위험 최소화", null],
      ["위험 판정", "protect", "위험 판정 F1", "위험 판정 Precision과 Recall의 조화평균", "높을수록 ↑", "94.2%", "2PR/(P+R)", null],
      ["개인정보 보호", "protect", "k 기준 위반율", "k 기준(5명 미만)을 위반한 환자 비율, 8턴 시점", "낮을수록 ↓", "0.8%", "예시 기준 ≤ 1.0% · 사전 정의 필요", done(pct(sel.violTurn7.p), state.arm === "C0" ? "" : "방어 없음 " + pct(base.violTurn7.p))],
      ["개인정보 보호", "protect", "재식별 성공률", "공격자가 개인을 다시 식별한 비율", "낮을수록 ↓", "2.4%", "공격 시나리오 기반", null],
      ["개인정보 보호", "protect", "민감 속성 추론 성공률", "공격자가 보호 대상 속성을 맞힌 비율", "낮을수록 ↓", "3.1%", "공격 시나리오 기반", null],
      ["유용성", "utility", "정보 유지율", "비식별화 후 보존된 유용 정보의 비율", "높을수록 ↑", "91.5%", "정보 가중치 정의",
        state.arm === "C0" ? null : done((state.arm === "C1" ? S.infoRetention.ours : S.infoRetention.single) + "%", "SynthPAI")],
      ["유용성", "utility", "정보 손실량", "비식별화로 사라지거나 손상된 정보량", "낮을수록 ↓", "8.5%", "정보 유지율과 함께 해석", null],
      ["유용성", "utility", "과잉 수정률", "불필요하게 수정·삭제된 안전 단서 비율", "낮을수록 ↓", "4.1%", "분모 정의 필요", done(pct(sel.overblock.p), "판정 " + sel.overblock.n.toLocaleString() + "건")],
      ["유용성", "utility", "후속 과업 성능 유지율", "비식별화 후 성능 ÷ 원문 기준 성능", "높을수록 ↑", "97.2%", "검색/분류/질의응답", null],
      ["유용성", "utility", "텍스트 유사도", "ROUGE·METEOR·BERTScore·임베딩 유사도", "높을수록 ↑", "BERTScore 0.94", "실제 과업 성능과 별도 보고", null],
      ["효율성", "speed", "평균 처리 시간", "요청 1건당 평균 처리 시간", "짧을수록 ↓", "0.011초", "측정 범위 명시", done(S.latency.meanSec + "초", "LLM 제외")],
      ["효율성", "speed", "p95 처리 시간", "처리 시간 분포의 95백분위수", "짧을수록 ↓", "0.028초", "측정 환경 명시", done(S.latency.p95Sec + "초", "LLM 제외")],
      ["효율성", "speed", "처리 비용", "요청 또는 문서당 처리 비용", "낮을수록 ↓", "₩3.2/건", "실제 비용으로 교체", null, "답을 고칠 때만 LLM 2회 추가"],
      ["종합 비교", "speed", "보호–활용 Pareto", "보호 수준과 활용성 사이의 상충관계 비교", "비교용", "비교 그래프", "보안 기준 충족 모델 중심", { st: "graph", t: "발표 40p 참고", note: "" }],
      ["종합 비교", "speed", "보조 복합 점수 E", "E = U × (1 − R)", "높을수록 ↑", "0.72", "가상 예시 · 표준 확립 지표 아님", null]
    ];
  }
  function renderAll() {
    const areas = ["전체", "단서 추출", "단서 유형별 보호", "위험 판정", "개인정보 보호", "유용성", "효율성", "종합 비교"];
    filterButtons("filters22", areas, "filter22", renderAll);
    const lab = { done: "측정됨", todo: "측정 전", graph: "그래프", demo: "예시" };
    const rows = allMetrics().filter((m) => state.filter22 === "all" || m[0] === state.filter22);
    document.querySelector("#allTable tbody").innerHTML = rows.map((m) => {
      const dcls = m[4].indexOf("↑") > -1 ? "up" : m[4].indexOf("↓") > -1 ? "down" : "neutral";
      let res, memo = m[6];
      if (state.demo) res = '<span class="state demo">예시</span><b style="display:inline">' + m[5] + "</b>";
      else if (m[7]) res = '<span class="state ' + m[7].st + '">' + lab[m[7].st] + "</span><b style=\"display:inline\">" + m[7].t + "</b>" + (m[7].note ? "<small>" + m[7].note + "</small>" : "");
      else { res = '<span class="state todo">측정 전</span>' + (m[8] ? "<small>" + m[8] + "</small>" : ""); }
      return '<tr><td><span class="pill ' + m[1] + '">' + m[0] + '</span></td><td class="metric left">' + m[2] + "</td><td>" + m[3] +
        '</td><td class="dir ' + dcls + '">' + m[4] + '</td><td class="res">' + res + '</td><td><span class="memo">' + memo + "</span></td></tr>";
    }).join("");
    $("foot3").textContent = state.demo
      ? "※ 예시값은 화면 시연용 가상 값이며 실제 실험 결과가 아닙니다. Precision·Recall·F1은 정답 단서의 범위(span)와 속성 일치 기준을 사전에 고정하세요."
      : "※ 측정된 항목만 값을 채웠습니다. 재식별·민감 속성 추론·복합 점수는 실험 설계와 위험 정의를 확정한 후 측정해야 합니다. 메모 열은 측정 방법·정의가 필요한 부분입니다.";
  }

  // ── 전체 다시 그리기 ──────────────────────────────────────
  function refresh() {
    renderMode(); renderFacts(); renderSeg(); renderCond(); renderKpis();
    renderMainTable(); renderChart(); renderArms(); renderAll();
  }
  $("armSel").addEventListener("change", (e) => { state.arm = e.target.value; refresh(); });
  $("demo").addEventListener("change", (e) => { state.demo = e.target.checked; renderKpis(); renderAll(); });
  window.addEventListener("hashchange", showTab);
  renderBars(); refresh(); showTab();
})();
