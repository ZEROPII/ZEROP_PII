// 백엔드 호출과 공용 도우미
const loading = () => document.getElementById("loading");
let busy = 0;

export async function api(path, { method = "GET", body, quiet = false } = {}) {
  if (!quiet) { busy++; loading().classList.remove("hidden"); }
  try {
    const res = await fetch(path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = new Error(typeof data.detail === "string" ? data.detail : `요청 실패 (${res.status})`);
      err.status = res.status;
      throw err;
    }
    return data;
  } finally {
    if (!quiet && --busy <= 0) { busy = 0; loading().classList.add("hidden"); }
  }
}

export function toast(msg, ms = 3800) {
  const t = document.createElement("div");
  t.className = "toast";
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), ms);
}

export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export function h(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

// k 상태: 위반(k<5) · 주의(5~10) · 여유
export function kStatus(k, kReq = 5) {
  if (k === 0) return { cls: "gray", label: "일치 없음" };
  if (k < kReq) return { cls: "bad", label: "위반" };
  if (k <= 10) return { cls: "warn", label: "주의" };
  return { cls: "ok", label: "여유" };
}
export const kChip = (k, kReq = 5) => {
  const s = kStatus(k, kReq);
  return `<span class="chip ${s.cls}">${s.label} · k ${k}</span>`;
};

export const pct = (p, d = 1) => (p == null ? "–" : `${(Math.round(p * 10 ** (d + 2) + 1e-6) / 10 ** d).toFixed(d)}%`);
export const ci = (c) => (c ? `[${(c[0] * 100).toFixed(1)}, ${(c[1] * 100).toFixed(1)}]` : "");

export const ARM_COLOR = { C0: "var(--c0)", C1: "var(--c1)", C1S: "var(--c1s)" };
export const ARM_HEX = { C0: "#C2521C", C1: "#1E5BB8", C1S: "#5AAEE6" };
export const ARM_NAME = { C0: "C0 방어 없음", C1: "C1 누적 State", C1S: "C1S 빈 State" };

// 받침에 맞는 목적격 조사
export function eul(word) {
  const c = word.charCodeAt(word.length - 1);
  if (c < 0xac00 || c > 0xd7a3) return `${word}을(를)`;
  return word + ((c - 0xac00) % 28 ? "을" : "를");
}

export const state = {
  meta: null,
  patients: null,
  sessionId: (() => { try { return sessionStorage.getItem("webdemo.sid"); } catch { return null; } })(),
  arm: "C1",
  setSession(id) {
    this.sessionId = id;
    try { id ? sessionStorage.setItem("webdemo.sid", id) : sessionStorage.removeItem("webdemo.sid"); } catch { /* 저장 안 돼도 됨 */ }
  },
};
