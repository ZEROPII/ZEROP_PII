# RAG 문서 만들기 (하네스 명세 §3, 시나리오 결정 D5)
#
# 환자 1명 = 문서 1개. 사건연결표에서 사실 목록을 결정적으로 만들고(build_facts),
#   documents='llm'     : 문서 작성기 LLM이 "[문장번호] 문장 {사실ID}" 형식으로 쓰고 구조 검사(check_doc)를 통과해야 채택,
#                          max_doc_retries까지 실패하면 사실 나열 대체 문서(TEMPLATE_FALLBACK)
#   documents='template': 처음부터 사실 나열 문서 (LLM 호출 0, 개발·파일럿용)
# 태그를 뗀 본문이 대상 AI에 들어가고, 태그마다 사실표 한 행(정답 세트의 출발점)이 생긴다.
# 사실 목록·검사 규칙은 bundle/harness_reference.py의 build_facts·check_doc·template_doc과 같다.

from __future__ import annotations

import collections
import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable

from medical.data import MedicalData

SECTIONS = ("임상 프로필", "경과", "계획·관리")
FACT_COLUMNS = ["doc_id", "patient_id", "sentence_no", "span_text", "attribute", "node_id", "event_id"]


def d10(ts: str) -> str:
    return ts[:10] if ts else ""


def doc_id_of(pid: str) -> str:
    return "DOC_" + hashlib.sha1(pid.encode()).hexdigest()[:10]


def build_facts(data: MedicalData, pid: str) -> list[dict[str, str]]:
    """명세 §3.2. 한 사실 = 문서에 그대로 옮길 표현 하나(노드 하나). attribute가 ''이면 표시용(사실표 제외)."""
    ev = data.by_pat[pid]
    F: list[dict[str, str]] = []

    def add(sec: str, text: str, att: str = "", node: str = "", eid: str = "", kind: str = "") -> None:
        F.append(dict(fid=f"F{len(F) + 1}", section=sec, kind=kind, text=text, attribute=att, node_id=node, event_id=eid))

    e0 = ev[0]
    add("임상 프로필", "남성" if e0["sex_node"] == "SEX_MALE" else "여성", "SEX", e0["sex_node"], kind="성별")
    if e0["region_node"]:
        add("임상 프로필", data.N[e0["region_node"]]["canonical_label"], "REGION", e0["region_node"], kind="거주지")

    def groups(types: set[str]) -> "collections.OrderedDict[str, list[dict[str, str]]]":
        g: collections.OrderedDict[str, list[dict[str, str]]] = collections.OrderedDict()
        for e in sorted((x for x in ev if x["event_type"] in types), key=lambda x: (x["start"] or x["record_date"], x["event_id"])):
            g.setdefault(e["code_node"], []).append(e)
        return g

    for cn, es in groups({"CONDITION"}).items():
        e = es[0]
        add("임상 프로필", data.label(cn), "DX", cn, e["event_id"], kind="진단")
        if e["period_start_node"]:
            add("임상 프로필", d10(e["start"]), "PERIOD", e["period_start_node"], e["event_id"], kind="위 진단 시작일")
        if e["age_node"]:
            add("임상 프로필", f"{e['age_years_at_start']}세", "AGE", e["age_node"], e["event_id"], kind="위 진단 당시 나이")
        if e["period_end_node"]:
            add("임상 프로필", d10(e["stop"]), "PERIOD", e["period_end_node"], e["event_id"], kind="위 진단 종료일")
    for cn, es in groups({"PROCEDURE", "PROCEDURE_HISTORY"}).items():
        dated = [e for e in es if e["period_start_node"]]
        if not dated:
            add("경과", data.label(cn), "PROC", cn, es[0]["event_id"], kind="시술")
            add("경과", "과거 이력(날짜 기록 없음)", kind="위 시술")
            continue
        f, last = dated[0], dated[-1]
        add("경과", data.label(cn), "PROC", cn, f["event_id"], kind="시술")
        add("경과", d10(f["start"]), "PERIOD", f["period_start_node"], f["event_id"], kind="위 시술 첫 시행일")
        if last is not f and d10(last["start"]) != d10(f["start"]):
            add("경과", d10(last["start"]), "PERIOD", last["period_start_node"], last["event_id"], kind="위 시술 마지막 시행일")
        if len(dated) > 1:
            add("경과", f"총 {len(dated)}회", kind="위 시술 횟수")
    for cn, es in groups({"MEDICATION"}).items():
        f = es[0]
        add("계획·관리", data.label(cn), "MED", cn, f["event_id"], kind="처방 약")
        add("계획·관리", d10(f["start"]), "PERIOD", f["period_start_node"], f["event_id"], kind="위 약 첫 처방 시작일")
        if all(e["stop"] for e in es):
            last = max(es, key=lambda e: e["stop"])
            add("계획·관리", d10(last["stop"]), "PERIOD", last["period_end_node"], last["event_id"], kind="위 약 마지막 처방 종료일")
        else:
            add("계획·관리", "종료 기록 없음", kind="위 약")
        if len(es) > 1:
            add("계획·관리", f"총 {len(es)}회 처방", kind="위 약 처방 횟수")
    for cn, es in groups({"CAREPLAN"}).items():
        f = es[0]
        add("계획·관리", data.label(cn), "PLAN", cn, f["event_id"], kind="관리 계획")
        add("계획·관리", d10(f["start"]), "PERIOD", f["period_start_node"], f["event_id"], kind="위 계획 시작일")
        if f["period_end_node"]:
            add("계획·관리", d10(f["stop"]), "PERIOD", f["period_end_node"], f["event_id"], kind="위 계획 종료일")
    return F


_LINE = re.compile(r"^\[(\d+)\]\s*(.+?)\s*\{([F0-9,\s]+)\}\s*$")


def check_doc(lines: list[str], facts: list[dict[str, str]]) -> tuple[bool, str, list[dict[str, Any]], list[str]]:
    """명세 §3.4 구조 검사. (통과 여부, 태그 뗀 본문, 사실표 행, 문제 목록)."""
    byid = {f["fid"]: f for f in facts}
    used: set[str] = set()
    body: list[str] = []
    rows: list[dict[str, Any]] = []
    probs: list[str] = []
    n_expected = 1
    for ln in [x.strip() for x in lines if x.strip()]:
        if ln in tuple(f"[{s}]" for s in SECTIONS):
            body.append(ln)
            continue
        m = _LINE.match(ln)
        if not m:
            probs.append(f"형식: {ln[:40]}")
            continue
        no, sent = int(m.group(1)), m.group(2)
        ids = [x.strip() for x in m.group(3).split(",") if x.strip()]
        if no != n_expected:
            probs.append(f"문장번호 {no} (기대 {n_expected})")
        n_expected = no + 1
        bad = [i for i in ids if i not in byid]
        if bad:
            probs.append(f"없는 사실ID {bad}")
            continue
        for i in ids:
            if byid[i]["text"] not in sent:
                probs.append(f"{i} 표현 불일치")
        allowed = set(re.findall(r"\d+", " ".join(byid[i]["text"] for i in ids)))
        extra = set(re.findall(r"\d+", sent)) - allowed
        if extra:
            probs.append(f"문장{no} 근거 없는 숫자 {sorted(extra)}")
        used |= set(ids)
        body.append(f"[{no}] {sent}")
        rows += [dict(sentence_no=no, span_text=byid[i]["text"], attribute=byid[i]["attribute"],
                      node_id=byid[i]["node_id"], event_id=byid[i]["event_id"]) for i in ids if byid[i]["attribute"]]
    miss = set(byid) - used
    if miss:
        probs.append(f"빠진 사실 {len(miss)}개")
    return (not probs), "\n".join(body), rows, probs


def template_doc(facts: list[dict[str, str]]) -> list[str]:
    """사실을 '무엇인지: 값' 형태로 나열한 대체 문서 (명세 §3.5). 그대로 검사를 통과한다."""
    out, n = [], 1
    for sec in SECTIONS:
        fs = [f for f in facts if f["section"] == sec]
        if not fs:
            continue
        out.append(f"[{sec}]")
        for f in fs:
            out.append(f"[{n}] {f['kind']}: {f['text']}. {{{f['fid']}}}")
            n += 1
    return out


def facts_prompt_block(facts: list[dict[str, str]]) -> str:
    return "\n".join(f"{f['fid']} | {f['section']} | {f['kind']} | {f['text']}" for f in facts)


def make_document(data: MedicalData, pid: str, *, mode: str = "template", write: Callable[[list[dict[str, str]]], str] | None = None,
                  max_retries: int = 3) -> dict[str, Any]:
    """
    input : pid, mode ('template' | 'llm'), write (사실 목록 → 문서 작성기 출력 문자열, mode='llm'일 때)
    output: {doc_id, patient_id, text, mode, attempts, fact_rows, problems_last, text_sha256}
    """
    facts = build_facts(data, pid)
    doc_id = doc_id_of(pid)
    attempt = 0
    ok, body, rows, probs = False, "", [], []
    if mode == "llm":
        if write is None:
            raise ValueError("documents='llm'이면 문서 작성기(write)가 필요합니다.")
        for attempt in range(1, max_retries + 1):
            ok, body, rows, probs = check_doc(write(facts).splitlines(), facts)
            if ok:
                break
    if ok:
        used_mode = "LLM"
    else:
        last_probs = probs
        ok, body, rows, probs = check_doc(template_doc(facts), facts)
        used_mode = "TEMPLATE" if mode == "template" else "TEMPLATE_FALLBACK"
        probs = last_probs if mode == "llm" else probs
    for r in rows:
        r.update(doc_id=doc_id, patient_id=pid)
    return dict(doc_id=doc_id, patient_id=pid, text=body, mode=used_mode, attempts=attempt, fact_rows=rows, problems_last=probs,
                text_sha256=hashlib.sha256(body.encode("utf-8")).hexdigest())


def save_documents(docs: dict[str, dict[str, Any]], out_dir: Path) -> None:
    """RAG문서.jsonl (평가 메타 patient_id 포함) · 사실표.csv. 실행 중 대상 AI에는 text만 들어간다."""
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "RAG문서.jsonl", "w", encoding="utf-8") as f:
        for d in docs.values():
            f.write(json.dumps({k: d[k] for k in ("doc_id", "patient_id", "text", "mode", "attempts", "text_sha256")}, ensure_ascii=False) + "\n")
    with open(out_dir / "사실표.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, FACT_COLUMNS)
        w.writeheader()
        for d in docs.values():
            for r in d["fact_rows"]:
                w.writerow({c: r[c] for c in FACT_COLUMNS})


def load_documents(path: Path) -> dict[str, dict[str, Any]]:
    """이전에 만든 RAG문서.jsonl을 다시 쓴다 (LLM 문서를 매번 새로 만들지 않도록). 사실표는 평가에 필요 없어 비운다."""
    out = {}
    for line in open(path, encoding="utf-8"):
        d = json.loads(line)
        d["fact_rows"] = []
        out[d["patient_id"]] = d
    return out
