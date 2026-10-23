# 질문 쪽 (Privacy Fuzzer 의료판): Seed 선택·연산자·변형·검사 (하네스 명세 §5·§6, 설계 §9.8–9.27)
#
# 통제 조건(Controlled Uniform)만 구현한다 (명세 §11-4). 피드백 가중치를 쓰는 적응 조건은 통제 조건 결과를 본 뒤
# 한재이 파트(fuzzer/feedback.py 전략 선택)와 함께 정한다.
#   Seed      : 의료 O1·O2 140행 (v0.13-med). 적용 조건은 seed_select.target이 사례 A의 State로 판정
#   선택      : 이 trial에서 덜 쓴 variant(BASE·REPHRASE·REROUTE) → 아직 안 쓴 Seed → 균등 무작위 (하네스 v0.2)
#               선택 정책을 바꾸는 피드백 모드(fuzzer_proto 전략)는 medical/adaptive.py
#   연산자    : M1 Rephrase · M3 Context Reframing · M4 Indirect Reframing (REROUTE 행이면 M4 제외) 중 균등
#   변형기    : 채운 Seed 문장·목표 단서·목적·방식·주체·연산자 계약·역할만 받는다 (정답·문서·사실표는 주지 않음)
#   검사      : 구조(결정적) → 의미(LLM 검사기 JSON 6항목 모두 true). 실패하면 max_mutation_retries까지 재생성

from __future__ import annotations

import collections
import random
import re
import sys
from typing import Any, Callable

from medical.bundle.seed_select import fill, load_registry, target
from medical.config import MedicalConfig, MedicalPaths
from medical.llm import RoleLLM
from medical.prompts import OPERATOR_CONTRACT, PROMPTS, QUERY_ROLES
from medical.tracking import parse_json

CHECK_KEYS = ("same_target_qi", "same_objective", "same_subject", "no_new_value", "not_more_specific", "operator_followed")


def _truthy(v: Any) -> bool:
    return v is True or str(v).strip().upper() == "TRUE"


def gate_rows(rows: list[dict[str, Any]], main_experiment: bool) -> list[dict[str, Any]]:
    """본 실험 모드면 human_reviewed·enabled_for_main=True, development_only=False 행만 (설계 §8.58). 없으면 중단."""
    if not main_experiment:
        return rows
    ok = [r for r in rows if _truthy(r.get("human_reviewed")) and _truthy(r.get("enabled_for_main")) and not _truthy(r.get("development_only"))]
    if not ok:
        sys.exit("본 실험 모드인데 human_reviewed=True·enabled_for_main=True·development_only=False인 행이 없습니다 (설계 §8.58).")
    return ok


def load_seeds(paths: MedicalPaths, main_experiment: bool) -> list[dict[str, Any]]:
    return gate_rows(load_registry(paths.o1) + load_registry(paths.o2), main_experiment)


def load_case_queries(paths: MedicalPaths, main_experiment: bool) -> dict[str, list[dict[str, Any]]]:
    cq: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for r in gate_rows(load_registry(paths.case_queries), main_experiment):
        cq[r["query_type"]].append(r)
    return cq


def applicable_ops(seed: dict[str, Any], operators: tuple[str, ...]) -> list[str]:
    ops = list(operators)
    if seed.get("variant") == "REROUTE" and "M4" in ops:
        ops.remove("M4")       # REROUTE는 이미 다른 경로로 묻는 행 → 간접화 대상 아님 (설계 §9.12, 하네스 v0.2)
    return ops


def choose_seed(seeds: list[dict[str, Any]], state: dict[Any, str], node: dict[str, Any], children: dict[str, int],
                used: set[str], scen_count: collections.Counter, rng: random.Random) -> tuple[dict[str, Any], Any] | None:
    ok = [(s, t) for s in seeds for t in [target(s, state, node, children, True)] if t is not None]
    if not ok:
        return None
    m = min(scen_count[s["variant"]] for s, _ in ok)
    pool = [x for x in ok if scen_count[x[0]["variant"]] == m]
    fresh = [x for x in pool if x[0]["seed_id"] not in used]
    return rng.choice(fresh or pool)


def fill_seed(seed: dict[str, Any], key: Any, state: dict[Any, str], node: dict[str, Any], subject: str, event_text: dict[str, str]) -> str:
    return fill(seed, key, state, node, subject=subject, event_text=event_text)


def structural_check(q: str, base: str, sent: list[str]) -> list[str]:
    p = []
    if not q.strip():
        p.append("EMPTY")
    if re.search(r"\[[A-Z_]+\]", q):
        p.append("PLACEHOLDER_LEFT")
    if set(re.findall(r"\d+", q)) - set(re.findall(r"\d+", base)):
        p.append("NEW_NUMBER")
    if q.strip() in sent:
        p.append("DUPLICATE")
    if len(q) > 400:
        p.append("TOO_LONG")
    return p


def realize(llm: RoleLLM, cfg: MedicalConfig, seed_text: str, qi: str, objective: str, scenario: str, subject: str,
            op: str, role: str, sent: list[str]) -> tuple[str | None, list[dict[str, Any]]]:
    """변형기 → 구조 검사 → 의미 검사. (통과한 질문 또는 None, 시도 기록)."""
    tries: list[dict[str, Any]] = []
    for _ in range(cfg.max_mutation_retries):
        cand = llm.complete("mutator", PROMPTS["mutator"].format(
            seed_text=seed_text, qi=qi, objective=objective, scenario=scenario, subject=subject,
            operator_contract=OPERATOR_CONTRACT[op], role=QUERY_ROLES[role], extra=""), []).strip()
        sp = structural_check(cand, seed_text, sent)
        if sp:
            tries.append(dict(text=cand, structural=sp, semantic=None))
            continue
        v = parse_json(llm.complete("checker", PROMPTS["checker"].format(
            qi=qi, objective=objective, operator=op, operator_contract=OPERATOR_CONTRACT[op], seed_text=seed_text, mutant=cand), []), "object")
        tries.append(dict(text=cand, structural=[], semantic=v))
        if v and all(v.get(x) is True for x in CHECK_KEYS):
            return cand, tries
    return None, tries
