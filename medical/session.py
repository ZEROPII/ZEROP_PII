# 의료 trial 실행: 질의 환자 1명 × 실행 갈래(C0·C1·C1S) (하네스 명세 §5–§8 + 공개 게이트)
#
# 한 trial의 흐름
#   턴 0  사례 검색 질문(말투 실현 M1/M3) → 검색(상위 5, trial 동안 고정) → 대상 AI 원 응답 → 추출
#         ※ 턴 0의 질문·원 응답·원 응답 추출은 갈래 간에 공유한다 (같은 질문·같은 이력이라 결과가 같아야 함, 토큰 절약)
#   턴 1~ 사례 A State로 Seed·연산자 선택 → 변형기 → 검사 → 대상 AI 원 응답 → 추출 → 공개 게이트 → State 반영 → k
# 공개 게이트
#   C0  : 원 응답을 그대로 공개
#   C1  : 사례별 Defender 판정(누적 State 기준) → 바꿀 것이 있으면 재작성기 LLM → 다시 추출해 확인
#         → 실패하면 결정적 치환 → 그래도 실패하면 거절 문장
#   C1S : C1과 같되 Defender 판정·확인을 매 턴 빈 State에서 한다
#   원 응답 추출이 실패하면 C1·C1S는 위험을 판단할 수 없으므로 거절 문장을 공개한다 (fail-closed)
# State에는 공개된 응답에서 나온 관찰만 들어간다 (원 응답 관찰은 State에 넣지 않음).
# 종료 (명세 §8): NO_CASE · RISK_AT_TURN0 · RISK_REACHED · SATURATED · MUTATION_BUDGET · BUDGET · LLM_ERROR
#   위험 판정은 사례 A의 k: 직전 0이 아닌 k ≥ k_req → 이번 1 ≤ k < k_req (k = 0은 ZERO_MATCH, 성공 아님)

from __future__ import annotations

import collections
import json
import random
from dataclasses import dataclass, field
from typing import Any, Callable

from core.llm_client import LLMError
from medical.adaptive import FeedbackSelector
from medical.attack import applicable_ops, choose_seed, fill_seed, realize
from medical.bundle.kcalc import KCalc
from medical.bundle.normalize_bridge import Normalizer
from medical.config import MedicalConfig
from medical.data import MedicalData
from medical.defense import MedicalDefender, format_changes
from medical.llm import RoleLLM
from medical.prompts import PROMPTS, REFUSAL_TEXT
from medical.retrieval import code_sets, fill_case_query, panel_text, query_binding, retrieve
from medical.tracking import Case, CaseView, commit_view, known_cases_json, parse_json, view_of

ARMS = ("C0", "C1", "C1S")


@dataclass
class Context:
    """run 전체에서 공유. 정답 쪽(doc_patient)은 평가에서만 쓴다."""
    cfg: MedicalConfig
    data: MedicalData
    kc: KCalc
    nz: Normalizer
    defender: MedicalDefender
    docs: dict[str, dict[str, Any]]                  # STORE patient_id → 문서
    store_sets: dict[str, dict[str, set[str]]]
    seeds: list[dict[str, Any]]
    case_queries: dict[str, list[dict[str, Any]]]
    llm: RoleLLM
    versions: dict[str, Any] = field(default_factory=dict)

    @property
    def p_ref(self) -> int:
        return len(self.kc.by_pat)


@dataclass
class Prefix:
    """갈래 간 공유하는 턴 0."""
    trial_id: str
    query_patient: str
    query_type: str
    role: str
    binding: dict[str, Any]
    case_query_id: str
    base_text: str
    docs: list[dict[str, Any]]
    retrieval: list[tuple[str, float]]
    system: str
    op0: str
    q0: str
    tries0: list[dict[str, Any]]
    realization_fallback: bool
    raw0: str
    obs0: list[dict[str, Any]]
    extract_ok0: bool
    extract_tries0: int


def extract(ctx: Context, query: str, response: str, known: str, docs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool, int]:
    obs, n = None, 0
    for _ in range(ctx.cfg.max_extract_retries + 1):
        n += 1
        obs = parse_json(ctx.llm.complete("extractor", PROMPTS["extractor"].format(cases=known, query=query, response=response), [],
                                          docs=docs, response=response), "array")
        if obs is not None:
            break
    return [o for o in (obs or []) if isinstance(o, dict)], obs is not None, n


def make_prefix(ctx: Context, tid: str, qpid: str, qtype: str, role: str) -> Prefix:
    rng = random.Random(f"{ctx.cfg.seed}-{tid}")
    b = query_binding(ctx.data, qpid, qtype, rng)
    if b is None:
        raise ValueError(f"{qpid}는 {qtype} 유형의 질의 환자가 될 수 없습니다 (관련 항목 또는 진단 범주 없음).")
    cq = rng.choice(ctx.case_queries[qtype])
    base = fill_case_query(cq["template_text"], b)
    ret = retrieve(code_sets(ctx.data.by_pat[qpid], b["index_date"]), ctx.store_sets, ctx.cfg.top_k_retrieval)
    docs = [ctx.docs[p] for p, _ in ret]
    system = PROMPTS["target_system"].format(n=len(docs), panel=panel_text(b),
                                             cases="\n\n".join(f"[사례{i}]\n{d['text']}" for i, d in enumerate(docs, 1)))
    op0 = rng.choice(["M1", "M3"])
    q0, tries0 = realize(ctx.llm, ctx.cfg, base, "(사례 검색: 단서를 묻지 않음)", "CASE_RETRIEVAL", "-", "-", op0, role, [])
    fallback = q0 is None
    q0 = q0 or base
    raw0 = ctx.llm.complete("target", system, [{"role": "user", "content": q0}], docs=docs,
                            intent=dict(kind="RETRIEVAL", qtype=qtype, binding=b))   # intent는 모의 대상 AI(medical/simulate.py)만 읽는다
    obs0, ok0, n0 = extract(ctx, q0, raw0, "[]", docs)
    return Prefix(tid, qpid, qtype, role, b, cq["case_query_id"], base, docs, ret, system, op0, q0, tries0, fallback, raw0, obs0, ok0, n0)


@dataclass
class Release:
    text: str
    view: CaseView
    mode: str                         # RAW / REWRITTEN / REWRITTEN_FALLBACK / REFUSAL / REFUSAL_EXTRACTION_FAILED
    plans: list[dict[str, Any]]
    changes: list[dict[str, Any]]
    attempts: list[dict[str, Any]]
    utility: float | None
    extraction_tries: int             # 공개 응답 확인 추출 호출 수 (원 응답 추출 제외)


def _empty_view() -> CaseView:
    return CaseView({}, {}, {}, {}, [])


class ArmRun:
    """한 갈래의 대화 하나. Case 상태·대화 이력·Seed 사용 기록을 갖는다."""

    def __init__(self, ctx: Context, prefix: Prefix, arm: str, log: Callable[[dict[str, Any]], None]) -> None:
        if arm not in ARMS:
            raise ValueError(arm)
        self.ctx, self.p, self.arm, self.log = ctx, prefix, arm, log
        self.cases: dict[str, Case] = {}
        self.order: list[str] = []
        self.msgs: list[dict[str, str]] = []
        self.sent: list[str] = []
        self.utilities: list[float] = []
        self.release_modes: collections.Counter = collections.Counter()
        self.trial: dict[str, Any] = dict(
            trial_id=prefix.trial_id, arm=arm, query_patient=prefix.query_patient, query_type=prefix.query_type, role=prefix.role,
            case_query_id=prefix.case_query_id, binding=prefix.binding, retrieved_doc_ids=[d["doc_id"] for d in prefix.docs],
            retrieval_scores=[s for _, s in prefix.retrieval], mode=ctx.cfg.mode, outcome=None, risk_entry_turn=None,
            risk_at_turn0=False, versions=ctx.versions)

    # ── 공개 게이트 ──────────────────────────────────────────

    def _basis(self, ref: str) -> list[dict[str, Any]]:
        if self.arm == "C1" and ref in self.cases:
            return list(self.cases[ref].committed)
        return []          # C1S: 빈 State. (C0은 게이트를 거치지 않는다)

    def _verify(self, query: str, text: str) -> tuple[bool, CaseView | None, list[dict[str, Any]], int]:
        obs, ok, n = extract(self.ctx, query, text, known_cases_json(self.cases, self.order), self.p.docs)
        if not ok:
            return False, None, [dict(reason="EXTRACTION_FAILED")], n
        v = view_of(obs, text, query, self.ctx.nz)
        checks, passed = [], True
        for ref in v.case_refs:
            basis = self._basis(ref)
            k_bef = self.ctx.kc.k(basis)["k"] if basis else self.ctx.p_ref
            k_aft = self.ctx.kc.k(basis + v.disclosures[ref])["k"] if v.disclosures[ref] else k_bef
            need = min(self.ctx.defender.s + 1, k_bef)
            good = (k_aft >= need) if k_aft > 0 else (k_bef == 0)
            checks.append(dict(ref=ref, k_before=k_bef, k_after=k_aft, need=need, ok=good))
            passed = passed and good
        return passed, v, checks, n

    def release(self, query: str, raw: str, raw_obs: list[dict[str, Any]], raw_ok: bool) -> Release:
        raw_view = view_of(raw_obs, raw, query, self.ctx.nz)
        if self.arm == "C0":
            n_dec = sum(len(raw_view.disclosures[r]) for r in raw_view.case_refs)
            return Release(raw, raw_view, "RAW", [], [], [], 1.0 if n_dec else None, 0)
        if not raw_ok:
            return Release(REFUSAL_TEXT, _empty_view(), "REFUSAL_EXTRACTION_FAILED", [], [], [], None, 0)
        d = self.ctx.defender
        plans = [d.plan_case(ref, self._basis(ref), raw_view.disclosures[ref], raw_view.sources[ref]) for ref in raw_view.case_refs]
        decisions = [x for p in plans for x in p.decisions]
        changes = d.change_lines(plans)
        plan_dicts = [p.as_dict() for p in plans]
        if not changes:
            return Release(raw, raw_view, "RAW", plan_dicts, [], [], 1.0 if decisions else None, 0)
        util = round(sum(x.utility for x in decisions) / len(decisions), 4)
        attempts, n_ext = [], 0
        candidates = [("REWRITTEN", None)] * self.ctx.cfg.max_rewrite_retries + [("REWRITTEN_FALLBACK", "deterministic")]
        for mode, kind in candidates:
            if kind is None:
                text = self.ctx.llm.complete("rewriter", PROMPTS["rewriter"].format(changes=format_changes(changes), response=raw), [],
                                             plan=changes, response=raw).strip()
            else:
                from medical.defense import apply_changes_deterministic
                text = apply_changes_deterministic(raw, changes)
            ok, v, checks, n = self._verify(query, text)
            n_ext += n
            attempts.append(dict(mode=mode, text=text, ok=ok, checks=checks))
            if ok and v is not None:
                return Release(text, v, mode, plan_dicts, changes, attempts, util, n_ext)
        return Release(REFUSAL_TEXT, _empty_view(), "REFUSAL", plan_dicts, changes, attempts, 0.0 if decisions else None, n_ext)

    # ── 한 턴 ───────────────────────────────────────────────

    def _turn(self, turn: int, query: str, raw: str | None, raw_obs: list[dict[str, Any]] | None, raw_ok: bool | None,
              n_raw_ext: int, meta: dict[str, Any], intent: dict[str, Any] | None = None) -> dict[str, Any]:
        if raw is None:
            raw = self.ctx.llm.complete("target", self.p.system, self.msgs + [{"role": "user", "content": query}], docs=self.p.docs,
                                        intent=intent)
            raw_obs, raw_ok, n_raw_ext = extract(self.ctx, query, raw, known_cases_json(self.cases, self.order), self.p.docs)
        rel = self.release(query, raw, raw_obs or [], bool(raw_ok))
        # 방어 '전' 후보 응답의 k (평가 v7.2 case_k_val_candidate: 과잉 차단 분모). 원 응답 공개를 그 사례의 누적 State에 더한 값
        cand_k: dict[str, int] = {}
        if raw_ok:
            rv = view_of(raw_obs or [], raw, query, self.ctx.nz)
            for ref in rv.case_refs:
                base = list(self.cases[ref].committed) if ref in self.cases else []
                ds = base + rv.disclosures[ref]
                cand_k[ref] = self.ctx.kc.k(ds)["k"] if ds else self.ctx.p_ref
        self.msgs += [{"role": "user", "content": query}, {"role": "assistant", "content": rel.text}]
        self.sent.append(query)
        commit_view(rel.view, self.cases, self.order)
        self.release_modes[rel.mode] += 1
        if rel.utility is not None:
            self.utilities.append(rel.utility)
        cases_out: dict[str, Any] = {}
        for ref in self.order:
            c = self.cases[ref]
            res = self.ctx.kc.k(c.committed) if c.committed else {"k": self.ctx.p_ref, "flags": [], "state": {}}
            c.k_hist.append(res["k"])
            cases_out[ref] = dict(k=res["k"], k_candidate=cand_k.get(ref, res["k"]), flags=res["flags"], state=res.get("state", {}),
                                  partial=rel.view.partial.get(ref, False), normalized=rel.view.normalized.get(ref, []))
        if "UNCLEAR" in rel.view.normalized:
            cases_out["UNCLEAR"] = dict(normalized=rel.view.normalized["UNCLEAR"])
        rec = dict(meta, trial_id=self.p.trial_id, arm=self.arm, turn=turn, query_text=query, raw_response_text=raw,
                   response_text=rel.text, release_mode=rel.mode, release_plans=rel.plans, release_changes=rel.changes,
                   release_attempts=rel.attempts, turn_utility=rel.utility, extraction_ok=bool(raw_ok), extraction_tries=n_raw_ext,
                   release_extraction_tries=rel.extraction_tries, raw_observations=raw_obs, cases=cases_out,
                   cases_candidate_k=cand_k)
        self.log(rec)
        return rec

    def _finish(self, outcome: str, turns: int, n_attempts: int, n_invalid: int) -> dict[str, Any]:
        self.trial.update(outcome=outcome, turns=turns, mutation_attempts=n_attempts, invalid_mutations=n_invalid,
                          case_k={c: self.cases[c].k_hist for c in self.order},
                          case_committed={c: self.cases[c].committed for c in self.order},
                          mean_utility=round(sum(self.utilities) / len(self.utilities), 4) if self.utilities else None,
                          release_modes=dict(self.release_modes))
        return self.trial

    def run(self) -> dict[str, Any]:
        cfg, p = self.ctx.cfg, self.p
        n_attempts = n_invalid = 0
        try:
            self._turn(0, p.q0, p.raw0, p.obs0, p.extract_ok0, p.extract_tries0,
                       dict(seed_id=None, case_query_id=p.case_query_id, operator=p.op0, realization_fallback=p.realization_fallback,
                            checks=p.tries0, regenerations=max(len(p.tries0) - 1, 0)))
            if not self.order:
                return self._finish("NO_CASE", 0, 0, 0)
            A = self.order[0]
            self.trial["case_A"] = A
            k0 = self.cases[A].k_hist[-1]
            k_prev = k0 if k0 > 0 else self.ctx.p_ref
            if 1 <= k0 < cfg.k_req:
                self.trial["risk_at_turn0"] = True
                if cfg.mode == "efficiency":
                    return self._finish("RISK_AT_TURN0", 0, 0, 0)
            rng = random.Random(f"{cfg.seed}-{p.trial_id}-follow")      # 갈래마다 같은 난수열 (State가 같으면 같은 Seed)
            used: set[str] = set()
            scen: collections.Counter = collections.Counter()
            selector = FeedbackSelector(threshold=cfg.k_req) if cfg.fuzzer == "feedback" else None
            turn = 0
            while turn < cfg.budget_B:
                if n_attempts >= cfg.attempt_budget:
                    return self._finish("MUTATION_BUDGET", turn, n_attempts, n_invalid)
                state = self.ctx.kc.reduce(self.cases[A].committed)[0]
                if selector is not None:
                    pick = selector.choose(self.ctx.seeds, state, self.ctx.kc.node, self.ctx.data.children, used, scen, rng)
                else:
                    pick = choose_seed(self.ctx.seeds, state, self.ctx.kc.node, self.ctx.data.children, used, scen, rng)
                if pick is None:
                    return self._finish("SATURATED", turn, n_attempts, n_invalid)
                seed, key = pick
                op = rng.choice(applicable_ops(seed, cfg.operators))
                evtxt = {f"{A}:{g}": v for g, v in self.cases[A].events.items()}
                subj = f"{A} 환자" if seed.get("scope") != "GROUP" else "검색된 사례 전체"     # 하네스 v0.2: GROUP 행은 사례 전체에 묻는다
                filled = fill_seed(seed, key, state, self.ctx.data.N, subj, evtxt)
                q, tries = realize(self.ctx.llm, cfg, filled, seed["target_qi"], seed["attack_objective"], seed["variant"],
                                   subj, op, p.role, self.sent)
                n_attempts += len(tries)
                if q is None:
                    n_invalid += 1
                    self.log(dict(trial_id=p.trial_id, arm=self.arm, turn=None, invalid_mutation=True, seed_id=seed["seed_id"],
                                  operator=op, filled_seed=filled, checks=tries))
                    continue
                turn += 1
                used.add(seed["seed_id"])
                scen[seed["variant"]] += 1
                self._turn(turn, q, None, None, None, 0, dict(seed_id=seed["seed_id"], target_qi=seed["target_qi"],
                                                               target_qi_2=seed.get("target_qi_2"), variant=seed["variant"],
                                                               scope=seed.get("scope"), relation=seed.get("expected_relation"),
                                                               objective=seed["attack_objective"], operator=op, filled_seed=filled,
                                                               realization_fallback=False, checks=tries, regenerations=len(tries) - 1,
                                                               fuzzer=cfg.fuzzer, fuzzer_strategy=selector.strategy if selector else None),
                           intent=dict(kind="FOLLOW", seed=seed, key=key, case_A=A, qtype=p.query_type,
                                       said={r: [d["node_id"] for d in c.committed] for r, c in self.cases.items()},
                                       events={r: list(c.events) for r, c in self.cases.items()}))
                k_before_turn = self.cases[A].k_hist[-2] if len(self.cases[A].k_hist) > 1 else self.ctx.p_ref
                k = self.cases[A].k_hist[-1]
                if selector is not None:
                    selector.observe(k_before_turn, k)
                if self.trial["risk_entry_turn"] is None and k_prev >= cfg.k_req and 1 <= k < cfg.k_req:
                    self.trial["risk_entry_turn"] = turn
                    if cfg.mode == "efficiency":
                        return self._finish("RISK_REACHED", turn, n_attempts, n_invalid)
                if k > 0:
                    k_prev = k
            return self._finish("BUDGET", turn, n_attempts, n_invalid)
        except LLMError as exc:
            self.trial["error"] = f"{type(exc).__name__}: {exc}"
            return self._finish("LLM_ERROR", len([m for m in self.msgs if m["role"] == "user"]) - 1, n_attempts, n_invalid)


def run_trial_group(ctx: Context, tid: str, qpid: str, qtype: str, role: str, arms: tuple[str, ...],
                    log: Callable[[dict[str, Any]], None]) -> list[dict[str, Any]]:
    """질의 환자 1명에 대해 갈래들을 차례로 실행한다 (턴 0 공유)."""
    try:
        prefix = make_prefix(ctx, tid, qpid, qtype, role)
    except LLMError as exc:
        return [dict(trial_id=tid, arm=a, query_patient=qpid, query_type=qtype, role=role, outcome="LLM_ERROR",
                     error=f"{type(exc).__name__}: {exc}", versions=ctx.versions) for a in arms]
    return [ArmRun(ctx, prefix, a, log).run() for a in arms]


def json_default(o: Any) -> Any:
    if isinstance(o, set):
        return sorted(o)
    return str(o)


def dumps(rec: dict[str, Any]) -> str:
    return json.dumps(rec, ensure_ascii=False, default=json_default)
