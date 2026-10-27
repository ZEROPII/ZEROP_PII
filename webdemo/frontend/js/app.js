// 화면 전환 (#/clinician · #/security · #/redteam · #/poc)
import { api, state, toast } from "./api.js";
import * as clinician from "./clinician.js";
import * as security from "./security.js";
import { mountPoc, mountRedteam } from "./results.js";

const routes = {
  clinician: (el) => clinician.mount(el),
  security: (el) => security.mount(el),
  redteam: (el) => mountRedteam(el),
  poc: (el) => mountPoc(el),
};
let current = null;

function setArmPill() {
  const pill = document.getElementById("modePill");
  pill.classList.toggle("off", state.arm === "C0");
  document.getElementById("modeText").textContent = state.arm === "C0" ? "보호 끔" : `보호 모드 · k > ${state.meta.generalize_threshold} 유지`;
  pill.style.visibility = current === "clinician" || current === "security" ? "visible" : "hidden";
}

async function route() {
  const name = (location.hash.replace("#/", "") || "clinician").split("?")[0];
  current = routes[name] ? name : "clinician";
  document.querySelectorAll(".nav a").forEach((a) => a.classList.toggle("on", a.dataset.route === current));
  setArmPill();
  const view = document.getElementById("view");
  view.innerHTML = "";
  try { await routes[current](view); } catch (e) { console.error(e); toast(e.message); }
}

async function boot() {
  try {
    [state.meta, state.patients] = await Promise.all([api("/api/meta"), api("/api/patients")]);
  } catch (e) {
    document.getElementById("view").innerHTML = `<div class="empty">서버에 연결하지 못했습니다: ${e.message}</div>`;
    return;
  }
  document.getElementById("targetNote").textContent = `대상 AI: 결정적 응답기 · 기준 집단 ${state.meta.p_ref}명 · LLM 호출 없음`;
  const sel = document.getElementById("armSelect");
  sel.value = state.arm;
  sel.addEventListener("change", async () => {
    state.arm = sel.value;
    setArmPill();
    if (current === "clinician") await clinician.refresh(true);
    if (current === "security") await security.refresh();
  });
  window.addEventListener("hashchange", route);
  route();
}

boot();
