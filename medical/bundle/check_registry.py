# -*- coding: utf-8 -*-
"""의료 Seed Registry v0.13 자동 검사 (Pass 1 구조 + Pass 3 교차 비교).
사용: python3 check_v013.py <O1.xlsx> <O2.xlsx> [노드_v0.10.csv]  (노드표를 주면 정답 라벨 혼입 검사도 함)
Pass 1: 필수 필드, 단서별 9행(BASE 1·REPHRASE 4·REROUTE 4), objective·자리표시자·조건·relation·gate 일치.
Pass 3: 완전 중복 없음, 같은 단서 안 유사도 0.95 미만, 숫자·온톨로지 라벨 없음, O1↔O2 자리표시자 분리,
        scope와 [SUBJECT] 일치, 재검증 3축이 단서·목적마다 모두 존재.
Pass 2(의미)는 이 스크립트가 대신하지 않는다 — 별도 검토 기록을 따른다."""
import sys, csv, re, collections, difflib, openpyxl

REQ = ["seed_id", "seed_version", "target_qi", "attack_objective", "variant", "scope", "template_text",
       "required_state_condition", "target_specificity_level", "allowed_placeholders", "expected_relation",
       "gt_independent", "human_reviewed", "status", "development_only", "enabled_for_main"]
QI = {"O1": ["AGE", "SEX", "REGION", "DX", "PROC", "PERIOD", "MED", "PLAN"],
      "O2": ["AGE", "REGION", "DX", "PROC", "PERIOD", "MED", "PLAN"]}
EVENT_QI = ("AGE", "DX", "PROC", "PERIOD", "MED", "PLAN")
COMP = {"BASE": 1, "REPHRASE": 4, "REROUTE": 4}
PRIOR = ("아까", "앞서", "하셨는데", "하신 건", "말씀하신", "라고 하셨", "알고 있습니다", "알고 있어요")

def load(p):
    ws = openpyxl.load_workbook(p, data_only=True).worksheets[0]
    rows = list(ws.iter_rows(values_only=True)); h = rows[0]
    return [dict(zip(h, r)) for r in rows[1:] if r[0]]

def labels(nodes):
    out = set()
    if not nodes: return out
    for n in csv.DictReader(open(nodes, encoding="utf-8-sig")):
        l = n["canonical_label"].strip()
        if n["attribute"] in ("REGION", "DX", "PROC", "MED", "PLAN") and len(l) >= 4 and not n["node_id"].endswith("ANY"):
            out.add(l.lower())
    return out

EXTRA = lambda r: ("-C" in r["seed_id"]) or ("-L" in r["seed_id"])   # v0.13 추가 행(단서별 9행 구조 밖)
def check(o1, o2, labs):
    res = []
    add = lambda n, ok, d=None: res.append((n, bool(ok), d or []))
    extra = [r for r in o1 + o2 if EXTRA(r)]
    o1 = [r for r in o1 if not EXTRA(r)]; o2 = [r for r in o2 if not EXTRA(r)]
    for obj, rows in (("O1", o1), ("O2", o2)):
        miss = [r["seed_id"] for r in rows if any(r.get(k) in (None, "") for k in REQ)]
        add(f"P1 {obj} 필수 필드", not miss, miss[:3])
        comp = collections.Counter((r["target_qi"], r["variant"]) for r in rows)
        bad = [(q, v, comp[(q, v)]) for q in QI[obj] for v, n in COMP.items() if comp[(q, v)] != n]
        add(f"P1 {obj} 구성 단서별 BASE 1·REPHRASE 4·REROUTE 4 ({len(QI[obj])}×9={len(QI[obj])*9})",
            not bad and len(rows) == len(QI[obj]) * 9, bad[:3])
        e = []
        for r in rows:
            t, c = r["template_text"], r["required_state_condition"]
            ph = set(re.findall(r"\[[A-Z_]+\]", t))
            if obj == "O1":
                ok = (r["attack_objective"] == "NEW_QI_ACQUISITION" and ph <= {"[SUBJECT]"}
                      and r["expected_relation"] == "NEW" and c.startswith(f"{r['target_qi']} not active"))
            else:
                linked = r["expected_relation"] == "LINKED_EVENT"
                ok = (r["attack_objective"] == "SPECIFICITY_REFINEMENT" and ph <= {"[SUBJECT]", "[PREVIOUSLY_DISCLOSED_QI]"}
                      and r["expected_relation"] in ("DESCENDANT", "LINKED_EVENT") and "active_node_has_descendant = true" in c
                      and "active_node_is_root = false" in c
                      and (("refine_same_event_ref = true" in c) == (r["target_qi"] in EVENT_QI and not linked)))
                # LINKED_EVENT는 다른 단서 경유 REROUTE에만
                ok = ok and (not linked or (r["variant"] == "REROUTE" and r.get("via_qi")))
                # REROUTE는 공개값을 인용하지 않아도 된다. 그 밖의 행은 반드시 인용한다.
                ok = ok and (("[PREVIOUSLY_DISCLOSED_QI]" in ph) or r["variant"] == "REROUTE")
            ok = ok and (("prior_context_available = true" in c) == any(k in t for k in PRIOR))
            ok = ok and str(r["gt_independent"]) == "True" and (str(r["human_reviewed"]) == "False" or r.get("status") == "HUMAN_REVIEWED_CANDIDATE") and str(r["enabled_for_main"]) == "False"
            ok = ok and (("[SUBJECT]" in ph) == (r["scope"] == "CASE"))
            ok = ok and r["allowed_placeholders"] == (";".join(sorted(ph)) if ph else "NONE")
            # 다른 단서 경유 표시는 REROUTE에만, via_qi와 link는 함께, via_qi는 목표와 다른 단서
            via, link = (r.get("via_qi") or ""), (r.get("link") or "")
            ok = ok and (bool(via) == bool(link)) and (not via or (r["variant"] == "REROUTE" and via != r["target_qi"]
                         and via in ("DX", "PROC", "MED", "PLAN") and link in ("SAME_ENCOUNTER", "SAME_PATIENT")
                         and bool(r.get("via_basis"))))   # v0.10: 경유 행은 근거(via_basis) 필수
            if not ok: e.append(r["seed_id"])
        add(f"P1 {obj} objective·자리표시자·조건·relation·gate·scope", not e, e[:4])

    allr = o1 + o2 + extra
    # v0.13 추가 행 검사: 단서 두 개 행은 조건이 둘 다 미공개여야 하고, 수준 지정 행은 answer_level이 계층에 있는 값이어야 한다
    ex = []
    for r in extra:
        if r.get("target_qi_2"):
            if not (r["required_state_condition"] == f"{r['target_qi']} not active AND {r['target_qi_2']} not active"
                    and r["attack_objective"] == "NEW_QI_ACQUISITION" and r["target_qi_2"] != r["target_qi"]): ex.append(r["seed_id"])
        elif r.get("answer_level"):
            if r["answer_level"] not in ("YEAR", "QUARTER", "MONTH", "DAY") or r["target_qi"] != "PERIOD": ex.append(r["seed_id"])
        else: ex.append(r["seed_id"])
    # 수준 지정 행은 수준을 가리키는 말만 다르고 나머지는 같아야 한다(다른 변인이 섞이면 수준 효과를 분리할 수 없음)
    lvr = [r for r in extra if r.get("answer_level")]
    norm = lambda t: re.sub(r"(월|연|분기|일)\s*단위", "〈수준〉 단위", t)
    add(f"P1 수준 지정 행 {len(lvr)}개: 수준 표현만 다르고 나머지 문장은 동일",
        len({norm(r["template_text"]) for r in lvr}) == 1 if lvr else True,
        sorted({norm(r["template_text"]) for r in lvr})[:2])
    add(f"P1 추가 행 {len(extra)}개: 단서 두 개는 둘 다 미공개 조건 · 수준 지정은 PERIOD 계층 값", not ex, ex[:3])
    dup = [t[:28] for t, v in collections.Counter(r["template_text"] for r in allr).items() if v > 1]
    add("P3 완전 중복 없음", not dup, dup[:3])
    near = []
    cell = collections.defaultdict(list)
    for r in allr: cell[(r["attack_objective"], r["target_qi"])].append(r)
    for rs in cell.values():
        for i in range(len(rs)):
            for j in range(i + 1, len(rs)):
                # 수준 지정 행끼리는 답변 수준만 달라야 하므로(월/연) 유사도 예외. 그 대신 '수준만 다른가'를 따로 본다
                lv = rs[i].get("answer_level") and rs[j].get("answer_level") and rs[i]["answer_level"] != rs[j]["answer_level"]
                s = difflib.SequenceMatcher(None, rs[i]["template_text"], rs[j]["template_text"]).ratio()
                if s >= 0.95 and not lv: near.append((rs[i]["seed_id"], rs[j]["seed_id"], round(s, 2)))
    add("P3 같은 단서 안 유사도 < 0.95", not near, near[:3])
    gt = [r["seed_id"] for r in allr if re.search(r"\d", r["template_text"])
          or any(l in r["template_text"].lower() for l in labs)]
    add(f"P3 정답값 비포함 (숫자·라벨 {len(labs)}개)", not gt, gt[:3])
    cross = [r["seed_id"] for r in o1 if "PREVIOUSLY" in r["template_text"]]
    add("P3 O1에 O2 자리표시자 없음", not cross, cross[:3])
    # 재검증 3축이 단서·목적마다 모두 있는지 (같은 질문/바꾼 표현/바꾼 순서를 항상 고를 수 있어야 함)
    miss3 = [(k, v) for k in cell for v in COMP if not any(r["variant"] == v for r in cell[k])]
    add("P3 재검증 3축 모두 존재 (단서×목적)", not miss3, miss3[:3])
    # Track B (v0.10): 사건 단서 6개(AGE·PERIOD·DX·PROC·MED·PLAN)는 O1·O2 모두 다른 단서 경유 행이 1~2개.
    # 근거가 약한 칸만 1개(경유_근거 시트). REGION·SEX는 경유할 사건이 없어 0개.
    nb = {k: sum(bool(r.get("via_qi")) for r in rs) for k, rs in cell.items()}
    needB = [(k, n) for k, n in nb.items() if (k[1] in ("AGE", "PERIOD", "DX", "PROC", "MED", "PLAN") and not 1 <= n <= 2)
             or (k[1] in ("REGION", "SEX") and n)]
    add(f"P3 사건 단서 6개 O1·O2마다 다른 단서 경유 1~2행 (계 {sum(nb.values())})", not needB, needB)
    # v0.11: REPHRASE 칸마다 문장 형식·명시성 두 수준이 모두 있는가 (문구_차원 시트)
    lack = []
    for k, rs in cell.items():
        rp = [r for r in rs if r["variant"] == "REPHRASE"]
        if {r.get("q_form") for r in rp} != {"QUESTION", "REQUEST"} or {r.get("explicitness") for r in rp} != {"GENERAL", "EXPLICIT"}:
            lack.append(k)
    add("P3 REPHRASE 칸마다 의문·요청 / 일반·명시 모두 존재", not lack, lack[:4])
    return res

if __name__ == "__main__":
    o1, o2 = load(sys.argv[1]), load(sys.argv[2])
    labs = labels(sys.argv[3] if len(sys.argv) > 3 else None)
    res = check(o1, o2, labs)
    for n, ok, d in res: print(("PASS " if ok else "FAIL ") + n + (f"  {d}" if d else ""))
    print(f"total {len(res)} fail {sum(not ok for _, ok, _ in res)}")
