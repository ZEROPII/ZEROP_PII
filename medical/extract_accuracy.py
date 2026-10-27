# 단서 추출 정확도 (LLM 0): 실행 기록의 대상 AI 원 응답 ↔ 추출기 출력 ↔ 사실표 정답
#
#   python -m medical.extract_accuracy <실행 폴더> [--reextract] [--out 결과.json]
#
# 정답(자동 대조, 사람 검토 전): 원 응답을 '사례N' 언급으로 나누고(‘사례1, 2, 3’처럼 묶어 말하면 모든 사례에 줌),
#   그 사례 문서의 사실표 값이 구간 안에 정해진 표기로 나오면 정답 단서 하나로 센다.
#     성별 남성·남자 / 여성·여자 · 지역 도시 이름 · 나이 'N세'·'N살' · 시점 날짜(YYYY-MM-DD, YYYY년 M월 D일 …)는 그날,
#     'YYYY년 M월'은 그 달(시점은 사실이 아니라 날짜 값으로 센다) · 진단·시술·약·관리 계획 기록 이름(대소문자 무시,
#     긴 이름부터 찾아 짧은 이름이 긴 이름 안에서 다시 잡히지 않게 함)
#   빼는 것: 주 이름만(모든 환자가 Massachusetts), 연도만(같은 해 사실이 여럿), 나이 범위('30대', '17-18세'),
#   바꿔 말한 표현('잇몸 염증'). 그래서 정답은 실제로 드러난 단서의 일부이고, 재현율은 '글자로 찾을 수 있는 단서' 기준이다.
# 추출: 기록된 raw_observations(또는 --reextract면 <실행 폴더>/reextract.jsonl의 observations)를 지금 tracking.view_of
#   (정규화·subject 보정)로 처리해 k 계산에 실제로 들어가는 값(commit)만 쓴다.
# 지표
#   답마다 재현율   : 정답 단서 중 같은 사례·같은 단서 종류로 그 노드 또는 상위 노드가 commit된 비율
#                     놓친 것은 '앞 턴에서 이미 뽑은 값의 재언급'(k 영향 없음)과 '새 값 누락'으로 나눈다
#   대화 재현율     : 대화(trial × 갈래) 전체에서 나온 정답 단서 중 한 번이라도 commit된 비율
#   정밀도          : commit된 값 중 그 사례 실제 환자 기록의 노드(정확) 또는 상위(덜 구체적)인 비율
# 결정적 응답기(medical.simulate) 실행은 추출기가 응답기의 줄 형식을 그대로 읽으므로 100%가 나온다. 실제 LLM 실행 기록에 쓴다.

from __future__ import annotations

import collections
import csv
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from medical.bundle.normalize_bridge import Normalizer
from medical.config import MedicalPaths
from medical.data import MedicalData
from medical.tracking import view_of
from medical.validate import own_nodes

ATTRS = ("SEX", "REGION", "AGE", "PERIOD", "DX", "PROC", "MED", "PLAN")
KO = dict(SEX="성별", REGION="지역", AGE="나이", PERIOD="시점", DX="진단", PROC="시술", MED="약", PLAN="관리 계획")
_CASE = re.compile(r"사례\s*(\d+)((?:\s*(?:,|·|및|와|과|/)\s*(?:사례\s*)?\d+)*)")


def _find(run_dir: Path, stem: str) -> Path:
    for f in run_dir.iterdir():
        if unicodedata.normalize("NFC", f.name) == stem:
            return f
    raise FileNotFoundError(f"{run_dir}/{stem}")


def sha(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def segments(text: str) -> dict[int, str]:
    marks = []
    for m in _CASE.finditer(text):
        marks.append((m.start(), [int(m.group(1))] + [int(x) for x in re.findall(r"\d+", m.group(2) or "")]))
    out: dict[int, list[str]] = collections.defaultdict(list)
    for i, (pos, nums) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        for n in nums:
            out[n].append(text[pos:end])
    return {n: "\n".join(v) for n, v in out.items()}


_DATE = re.compile(r"_(\d{4}(?:-\d{2}){0,2})$")


def node_date(node: str) -> str | None:
    """PERIOD 노드의 날짜 부분: ..._DAY_2018-01-13 → '2018-01-13', ..._MONTH_2018-01 → '2018-01', ..._YEAR_2018 → '2018'."""
    m = _DATE.search(node)
    return m.group(1) if m and node.startswith("PERIOD") else None


def truth_items(rows: list[dict[str, str]], seg: str, data: MedicalData) -> dict[tuple[str, str], dict[str, str]]:
    """한 사례 구간의 정답 단서. 키 = (단서, 값 키). 시점은 날짜 값으로 센다(같은 날짜가 진단 시작·처방 시작 등 여러 사실에 걸려도 한 번)."""
    out: dict[tuple[str, str], dict[str, str]] = {}
    # 진단·시술·약·관리 계획: 긴 이름부터 찾고 찾은 자리는 지운다 ('Gingivitis'가 'Chronic gingivitis' 안에서 다시 잡히지 않게)
    rest = seg.lower()
    names = sorted((r for r in rows if r["attribute"] in ("DX", "PROC", "MED", "PLAN") and r["span_text"]), key=lambda r: -len(r["span_text"]))
    for r in names:
        sp = r["span_text"].lower()
        pat = re.compile(rf"(?<![a-z0-9]){re.escape(sp)}(?![a-z0-9])")
        if pat.search(rest):
            out[(r["attribute"], r["node_id"])] = r
            rest = pat.sub(" ", rest)
    for r in rows:
        a, sp, node = r["attribute"], r["span_text"], r["node_id"]
        if a == "SEX":
            words = ("남성", "남자", "남아") if node == "SEX_MALE" else ("여성", "여자", "여아")
            if any(w in seg for w in words):
                out[(a, node)] = r
        elif a == "REGION":
            city = sp.split(",")[0].strip().lower()
            if city and re.search(rf"(?<![a-z]){re.escape(city)}(?![a-z])", seg.lower()):
                out[(a, node)] = r
        elif a == "AGE":
            n = re.sub(r"\D", "", sp)
            if n and re.search(rf"(?<!\d){n}\s*(세|살)", seg):
                out[(a, node)] = r
        elif a == "PERIOD":
            m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", sp)
            if not m:
                continue
            y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
            if any(x in seg for x in (sp, f"{y}.{mo:02d}.{d:02d}", f"{y}/{mo:02d}/{d:02d}", f"{y}년 {mo}월 {d}일", f"{y}년 {mo:02d}월 {d:02d}일")):
                out[(a, sp)] = r
            elif re.search(rf"{y}-{mo:02d}(?!-\d)|{y}년 {mo}월(?! ?\d+일)|{y}\.{mo:02d}(?!\.\d)", seg):
                out[(a, f"{y}-{mo:02d}")] = r
    return out


def caught(key: tuple[str, str], got: set[str], data: MedicalData) -> str | None:
    """정답 단서를 commit된 노드들이 잡았는지: 'exact' | 'broader' | None."""
    a, v = key
    if a == "PERIOD":
        dates = [x for x in (node_date(n) for n in got) if x]
        if any(x == v or x.startswith(v) for x in dates):
            return "exact"
        if any(v.startswith(x) for x in dates):
            return "broader"
        return None
    if v in got:
        return "exact"
    anc = set(data.anc(v)) if v in data.N else {v}
    return "broader" if anc & got else None


def measure(run_dir: Path, use_reextract: bool = False, data: MedicalData | None = None) -> dict[str, Any]:
    data = data or MedicalData()
    paths = MedicalPaths()
    nz = Normalizer(paths.nodes, paths.alias)
    recs = [json.loads(l) for l in open(_find(run_dir, "턴기록.jsonl"), encoding="utf-8")]
    recs = [r for r in recs if r.get("turn") is not None and r.get("raw_response_text")]
    trials = {(t["trial_id"], t["arm"]): t for t in json.loads(_find(run_dir, "trial요약.json").read_text(encoding="utf-8"))["trials"]}
    facts: dict[str, list[dict[str, str]]] = collections.defaultdict(list)
    for r in csv.DictReader(open(_find(run_dir, "사실표.csv"), encoding="utf-8-sig")):
        facts[r["doc_id"]].append(r)
    doc_patient = {d: rows[0]["patient_id"] for d, rows in facts.items()}
    re_obs: dict[str, list[dict[str, Any]]] = {}
    if use_reextract:
        for line in open(run_dir / "reextract.jsonl", encoding="utf-8"):
            x = json.loads(line)
            if "observations" not in x:
                raise ValueError("reextract.jsonl에 observations가 없습니다. python -m medical reextract를 다시 실행하세요.")
            re_obs[x["raw_sha"]] = x["observations"]

    def obs_of(r: dict[str, Any]) -> list[dict[str, Any]] | None:
        if use_reextract:
            return re_obs.get(sha(r["raw_response_text"]))
        return r.get("raw_observations") or []

    per = {a: collections.Counter() for a in ATTRS}
    cum = {a: collections.Counter() for a in ATTRS}
    prec = {a: collections.Counter() for a in ATTRS}
    examples: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    seen_prec: set[str] = set()
    answers: set[str] = set()
    skipped = 0
    conv: dict[tuple[str, str], list[dict[str, Any]]] = collections.defaultdict(list)
    for r in recs:
        conv[(r["trial_id"], r["arm"])].append(r)
    for (tid, arm), rs in sorted(conv.items()):
        rs.sort(key=lambda x: x["turn"])
        docs = trials[(tid, arm)]["retrieved_doc_ids"]
        known: dict[str, set[str]] = collections.defaultdict(set)
        gt_all: dict[str, set[tuple[str, str]]] = collections.defaultdict(set)
        for r in rs:
            obs = obs_of(r)
            if obs is None:
                skipped += 1
                continue
            text, query, h = r["raw_response_text"], r["query_text"], sha(r["raw_response_text"])
            first = h not in answers                       # 턴 0처럼 갈래끼리 같은 답은 '답마다' 지표에서 한 번만 센다
            answers.add(h)
            v = view_of(obs, text, query, nz)
            now = {ref: {d["node_id"] for d in v.disclosures.get(ref, [])} for ref in v.case_refs}
            for n, seg in segments(text).items():
                if not 1 <= n <= len(docs):
                    continue
                ref = f"사례{n}"
                gt = truth_items([x for x in facts[docs[n - 1]] if x["attribute"] in ATTRS], seg, data)
                for key, row in gt.items():
                    a = key[0]
                    gt_all[ref].add(key)
                    if not first:
                        continue
                    hit = caught(key, now.get(ref, set()), data)
                    per[a]["gt"] += 1
                    if hit:
                        per[a][hit] += 1
                    elif caught(key, known[ref], data):
                        per[a]["repeat_miss"] += 1
                    else:
                        per[a]["new_miss"] += 1
                        if len(examples[a]) < 5:
                            examples[a].append(dict(trial=tid, arm=arm, turn=r["turn"], case=ref, value=row["span_text"],
                                                    extractor_said=[o.get("raw_value") for o in obs if o.get("attribute") == a
                                                                    and re.sub(r"\D", "", str(o.get("case_ref"))) == str(n)][:3]))
            if first:
                for ref in v.case_refs:
                    m = re.fullmatch(r"사례(\d+)", ref)
                    if not m or not 1 <= int(m.group(1)) <= len(docs) or docs[int(m.group(1)) - 1] not in doc_patient:
                        continue
                    exact, anc = own_nodes(data, doc_patient[docs[int(m.group(1)) - 1]])
                    for d in v.disclosures[ref]:
                        prec[d["attribute"]]["n"] += 1
                        prec[d["attribute"]]["correct" if d["node_id"] in exact else "less" if d["node_id"] in anc else "wrong"] += 1
                for os_ in v.normalized.values():
                    for o in os_:
                        if o.get("attribute") in prec and not o.get("commit"):
                            prec[o["attribute"]]["not_committed"] += 1
            for ref, ns in now.items():
                known[ref] |= ns
        for ref, items in gt_all.items():
            for key in items:
                cum[key[0]]["gt"] += 1
                cum[key[0]]["hit" if caught(key, known[ref], data) else "miss"] += 1

    def ratio(x: int, n: int) -> float | None:
        return round(x / n, 4) if n else None

    rows = []
    for a in list(ATTRS) + ["ALL"]:
        p = per[a] if a != "ALL" else sum(per.values(), collections.Counter())
        c = cum[a] if a != "ALL" else sum(cum.values(), collections.Counter())
        q = prec[a] if a != "ALL" else sum(prec.values(), collections.Counter())
        rows.append(dict(attribute=a, label=KO.get(a, "전체"), gt=p["gt"], exact=p["exact"], broader=p["broader"],
                         repeat_miss=p["repeat_miss"], new_miss=p["new_miss"],
                         recall_answer=ratio(p["exact"] + p["broader"], p["gt"]),
                         conv_gt=c["gt"], conv_hit=c["hit"], recall_conversation=ratio(c["hit"], c["gt"]),
                         committed=q["n"], correct=q["correct"], less=q["less"], wrong=q["wrong"],
                         precision=ratio(q["correct"] + q["less"], q["n"]), not_committed=q["not_committed"]))
    return dict(run=str(run_dir), source="reextract" if use_reextract else "recorded", answers=len(answers),
                conversations=len(conv), trials=len({t for t, _ in conv}), skipped_records=skipped, rows=rows, new_miss_examples=examples)


def report(res: dict[str, Any]) -> str:
    pct = lambda x: "-" if x is None else f"{x * 100:.1f}%"
    lines = [f"답 {res['answers']}개 · 대화 {res['conversations']}개 (질의 환자 {res['trials']}명) · 추출 출처 {res['source']}",
             "| 단서 | 정답(답마다) | 맞음 | 재언급 누락 | 새 값 누락 | 답마다 재현율 | 대화 재현율 | commit | 틀림 | 정밀도 | 미반영 |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for x in res["rows"]:
        lines.append(f"| {x['label']} | {x['gt']} | {x['exact'] + x['broader']} | {x['repeat_miss']} | {x['new_miss']} | {pct(x['recall_answer'])} | "
                     f"{pct(x['recall_conversation'])} ({x['conv_hit']}/{x['conv_gt']}) | {x['committed']} | {x['wrong']} | {pct(x['precision'])} | {x['not_committed']} |")
    return "\n".join(lines)


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m medical.extract_accuracy")
    ap.add_argument("run_dir")
    ap.add_argument("--reextract", action="store_true", help="<실행 폴더>/reextract.jsonl의 다시 뽑은 결과로 잰다")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    res = measure(Path(a.run_dir), a.reextract)
    print(report(res))
    if a.out:
        Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
