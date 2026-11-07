# 운영 모드 진료 기준: 외래 환자의 '가장 최근 진료'로 진료 목적 · 환자 요약 · 유사 사례 검색을 만든다 (ADR-0029).
#
# 연구 계획(medical.retrieval.query_binding)은 질의 환자마다 '가장 많이 나온 진단 범주의 첫 진료'를 기준일로 삼는다.
# 연구 결과의 재현에는 맞지만, 운영 화면에서는 2026년까지 기록이 있는 환자의 진료 목적이 2017년 진료 하나에서 만들어지고
# (의료진 체험 2026-11-05: 'Acute bronchitis · 2017-07-31 진료 기준', 마지막 기록 2026-07-28), 그 날짜 뒤에 생긴
# 고혈압 · 고지혈증 같은 동반질환이 환자 요약 · 유사 사례 검색 어디에도 들어가지 않았다.
#
# visit_binding: 진료 목적마다 그 목적이 성립하는(관련 항목이 있는) 진단 사건 중 가장 최근 것을 기준 진료로 삼는다.
#   - 주진단 = 그 사건의 ICD 세 자리 범주. 관련 항목은 연구 규칙과 같다 (처방: 그날 쓰던 약, 시술: 그날 뒤 시술, 경과: 그날 뒤 약 · 관리 계획).
#     그날 시작한 항목(같은 진료에서 정한 것)이 있으면 그중에서 고른다.
#   - 동반질환 = 그날 이어지던(끝나지 않은) 다른 진단. 환자 요약(PANEL_COMORBIDITY)에는 많이 나온 두 범주를 쓴다 (연구와 같은 모양).
#   - 유사 사례 검색은 연구와 같이 그날까지의 진단 · 약 · 시술 기록 전체로 한다 (기준일이 최근이라 동반질환 · 복용약이 들어간다).
# make_prefix_with: medical.session.make_prefix와 같은 순서 · 같은 난수로 첫 답 요청을 만들되, 기준 진료만 바꿔 끼운다.
# 레드팀 · 연구 실행(plan_all, make_prefix)은 바꾸지 않는다.
#
# 오늘 진단 고르기 (ADR-0029 덧붙임): 가장 최근 진료와 오늘 볼 문제가 다를 수 있다(CKD 환자가 마지막에 치은염으로 온 경우).
# visit_binding(index_event=…)은 의사가 고른 진단 사건을 기준 진료로 쓴다. 고를 수 있는 목록은 engine.visit_choices
# (진단 이름마다 그 목적이 성립하는 가장 최근 사건, 최근 것부터).

from __future__ import annotations

import collections
import random
from typing import Any, Callable

from medical.attack import realize
from medical.prompts import PROMPTS
from medical.retrieval import PURPOSE, code_sets, fill_case_query, panel_text, retrieve
from medical.session import Context, Prefix, extract

Binder = Callable[[Any, str, str, random.Random], "dict[str, Any] | None"]


def _d10(ts: str | None) -> str:
    return ts[:10] if ts else ""


def _category(data: Any, node: str) -> str | None:
    return next((a for a in data.anc(node) if a.startswith("DX_ICD_CODE_") and len(data.N[a]["standard_code"]) == 3), None)


def _items(data: Any, ev: list[dict[str, str]], qtype: str, day: str) -> tuple[list[str], list[str]]:
    """(관련 항목, 그날 시작한 관련 항목). 연구 규칙(query_binding)과 같은 항목 정의."""
    def lab_of(e: dict[str, str], prefix: str) -> str | None:
        a = next((x for x in data.anc(e["code_node"]) if x.startswith(prefix)), None)
        return data.label(a) if a else None

    def med_of(e: dict[str, str]) -> str:
        return lab_of(e, "MED_IN_") or lab_of(e, "MED_DF_") or data.label(e["code_node"])

    if qtype == "PRESCRIPTION":
        pairs = [(med_of(e), e) for e in ev if e["event_type"] == "MEDICATION" and _d10(e["start"]) <= day and (not e["stop"] or _d10(e["stop"]) >= day)]
    elif qtype == "TREATMENT_PROCEDURE":
        pairs = [(lab_of(e, "PROC_GROUP_"), e) for e in ev if e["event_type"] == "PROCEDURE" and _d10(e["start"]) >= day]
    else:
        pairs = [(med_of(e), e) for e in ev if e["event_type"] == "MEDICATION" and _d10(e["start"]) >= day] + \
                [(data.label(e["code_node"]), e) for e in ev if e["event_type"] == "CAREPLAN" and _d10(e["start"]) >= day]
    items = sorted({i for i, _ in pairs if i})
    same_day = sorted({i for i, e in pairs if i and _d10(e["start"]) == day})
    return items, same_day


def diagnosis_events(data: Any, pid: str) -> list[tuple[dict[str, str], str]]:
    """(진단 사건, ICD 세 자리 범주). 범주가 없는 진단은 기준 진료가 될 수 없다 (검색 · 패널이 범주를 쓴다)."""
    return [(e, c) for e in data.by_pat[pid] if e["event_type"] == "CONDITION" for c in [_category(data, e["code_node"])] if c]


def visit_binding(data: Any, pid: str, qtype: str, rng: random.Random, index_event: str | None = None) -> dict[str, Any] | None:
    """
    가장 최근 진료 기준 (위 설명). index_event를 주면 그 진단 사건을 기준 진료로 쓴다 (오늘 진단 고르기).
    그 목적이 성립하는 진료가 없으면 None. query_binding과 같은 열쇠에 visit · active를 더한다.
    """
    ev = data.by_pat[pid]
    cond = diagnosis_events(data, pid)
    if not cond:
        return None
    pick = None
    for e, c in sorted(cond, key=lambda x: (_d10(x[0]["start"]), x[0]["event_id"]), reverse=True):
        if index_event is not None and e["event_id"] != index_event:
            continue
        items, same_day = _items(data, ev, qtype, _d10(e["start"]))
        if items:
            pick = (e, c, items, same_day)
            break
    if pick is None:
        return None
    idx, main, items, same_day = pick
    day = _d10(idx["start"])
    rel = rng.choice(same_day or items)
    active = [(e, c) for e, c in cond if c != main and _d10(e["start"]) <= day and (not e["stop"] or _d10(e["stop"]) >= day)]
    counts = collections.Counter(c for e, c in cond if c != main and _d10(e["start"]) <= day)
    co = sorted({c for _, c in active}, key=lambda c: (-counts[c], c))[:2]
    # 이름은 범주 이름('Disorders of lipoprotein metabolism …') 대신 그 범주의 가장 최근 진단 이름('Hyperlipidemia')
    latest = {c: data.label(e["code_node"]) for e, c in sorted(active, key=lambda x: _d10(x[0]["start"]))}
    main_label = data.label(idx["code_node"])
    age = int(idx["age_years_at_start"])
    sex = "남" if ev[0]["sex_node"] == "SEX_MALE" else "여"
    panel = dict(PANEL_AGE_SEX=f"{age}세 / {sex}", PANEL_MAIN_DX=main_label,
                 PANEL_COMORBIDITY=", ".join(latest[c] for c in co) or "없음", PANEL_CONSIDERED=rel, PANEL_PURPOSE=PURPOSE[qtype])
    return dict(QUERY_AGE_BAND=("10세 미만" if age < 10 else f"{age // 10 * 10}대"), QUERY_SEX="남성" if sex == "남" else "여성",
                QUERY_MAIN_DX=main_label, QUERY_RELATED_ITEM=rel, index_event=idx["event_id"], index_date=day, main_dx_node=main,
                panel=panel, visit="chosen" if index_event is not None else "recent",
                active=sorted({data.label(e["code_node"]) for e, _ in active}))


def make_prefix_with(ctx: Context, tid: str, qpid: str, qtype: str, role: str, binder: Binder, *,
                     cases_text: Callable[[list[dict[str, Any]]], str] | None = None,
                     exclude: "set[str] | frozenset[str]" = frozenset()) -> Prefix:
    """
    medical.session.make_prefix와 같은 순서 · 같은 난수 (query_binding 자리에 binder).
    cases_text(docs): 대상 AI 지시문의 [검색된 사례] 자리 글 (입력 게이팅, gate.py). 없으면 문서 원문을 그대로 (지금까지와 같음).
    exclude: 유사 사례 검색에서 뺄 과거 환자 (민감도 정책, sensitivity.py). 후보 수의 기준 집단에서는 빼지 않는다.
    """
    rng = random.Random(f"{ctx.cfg.seed}-{tid}")
    b = binder(ctx.data, qpid, qtype, rng)
    if b is None:
        raise ValueError(f"{qpid}는 {qtype} 유형의 질의 환자가 될 수 없습니다 (관련 항목 또는 진단 범주 없음).")
    cq = rng.choice(ctx.case_queries[qtype])
    base = fill_case_query(cq["template_text"], b)
    store_sets = {p: s for p, s in ctx.store_sets.items() if p not in exclude} if exclude else ctx.store_sets
    ret = retrieve(code_sets(ctx.data.by_pat[qpid], b["index_date"]), store_sets, ctx.cfg.top_k_retrieval)
    docs = [ctx.docs[p] for p, _ in ret]
    cases = cases_text(docs) if cases_text is not None else "\n\n".join(f"[사례{i}]\n{d['text']}" for i, d in enumerate(docs, 1))
    system = PROMPTS["target_system"].format(n=len(docs), panel=panel_text(b), cases=cases)
    op0 = rng.choice(["M1", "M3"])
    q0, tries0 = realize(ctx.llm, ctx.cfg, base, "(사례 검색: 단서를 묻지 않음)", "CASE_RETRIEVAL", "-", "-", op0, role, [])
    fallback = q0 is None
    q0 = q0 or base
    raw0 = ctx.llm.complete("target", system, [{"role": "user", "content": q0}], docs=docs,
                            intent=dict(kind="RETRIEVAL", qtype=qtype, binding=b))
    obs0, ok0, n0 = extract(ctx, q0, raw0, "[]", docs)
    return Prefix(tid, qpid, qtype, role, b, cq["case_query_id"], base, docs, ret, system, op0, q0, tries0, fallback, raw0, obs0, ok0, n0)
