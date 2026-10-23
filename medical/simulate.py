# 모의 대상 AI로 의료 POC 돌리기 (LLM 호출 0, 결정적)
#
# 왜 필요한가: 실제 대상 AI 실험은 LLM 키가 있는 환경에서만 돌릴 수 있다. 그 전에 의료 파이프라인 전체
#   (사례 검색 → 질문 Seed → 대상 AI 답변 → 추출 → 정규화 → 사례별 kcalc k → Defender → 재작성 → State → Validated k → 평가)
#   가 '질문에 순순히 답하는 AI'를 상대로 어떤 결과를 내는지 미리 재 본다. 결과는 대상 AI 성향을 가정한 값이다.
#
# 가정 (결과를 읽을 때 꼭 함께 밝힌다)
#   대상 AI   : 묻는 단서를 검색된 사례 문서에 있는 값으로 항상 답한다 (거절·환각·사례 혼동 없음).
#               profile='staged'(단계 공개형, 기본) — 처음 묻는 나이는 10세 구간, 날짜는 연, 지역은 주까지만 말하고,
#                 '더 구체적으로'(O2 DESCENDANT·LINKED_EVENT) 물으면 기록 그대로 말한다. 진단·시술·약·계획 이름은 기록 그대로.
#                 Seed가 답 수준을 정한 행(answer_level MONTH·YEAR)은 그 수준으로.
#               profile='full'(전면 공개형) — 처음부터 기록 그대로(1세·일·도시).
#               턴 0(사례 검색)에서는 사례마다 질의 환자 주진단과 같은 범주의 진단 하나, 조회 유형의 관련 항목 하나(약·시술·계획)를 말한다.
#   추출기    : 답변의 값을 빠짐없이, 사건 연결까지 정확히 뽑는다 (추출 오류 0).
#   재작성기  : Defender 변경 목록을 해당 사례·해당 단서의 값에만 정확히 적용한다.
#   변형기·검사기 : Seed 문장을 그대로 쓴다 (M1·M3·M4 연산자 효과는 이 POC에서 재지 않는다).
# 대상 AI만 문서를 보고, 추출기·재작성기는 대상 AI가 답변에 붙인 줄 구조만 본다. 정답(사실표 전체)은 Validated k 계산에서만 쓴다.

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from medical.data import MedicalData
from medical.llm import MockRoleLLM

KIND = {"DX": "진단", "PROC": "시술", "MED": "처방 약", "PLAN": "관리 계획"}
ITEM_ATTR = {"PRESCRIPTION": ("MED",), "TREATMENT_PROCEDURE": ("PROC",), "COURSE_CARE": ("PLAN", "MED")}
_LINE = re.compile(r"^(사례\d+) · (.+?): (.+)$")
SUPPRESSED = "(비공개)"


def _case_no(ref: str) -> int:
    return int(re.sub(r"\D", "", ref))


@dataclass
class _Doc:
    """문서 하나의 사실을 사건별로 묶은 것 (대상 AI가 보는 문서 내용 그대로)."""
    doc: dict[str, Any]
    sex: dict[str, Any] | None = None
    region: dict[str, Any] | None = None
    events: dict[str, dict[str, list[dict[str, Any]]]] = field(default_factory=dict)   # event_id → attribute → 사실 행
    order: list[str] = field(default_factory=list)                                     # 사건이 문서에 처음 나온 순서

    @classmethod
    def of(cls, doc: dict[str, Any]) -> "_Doc":
        d = cls(doc)
        for r in doc["fact_rows"]:
            if r["attribute"] == "SEX":
                d.sex = r
            elif r["attribute"] == "REGION":
                d.region = r
            elif r["event_id"]:
                if r["event_id"] not in d.events:
                    d.events[r["event_id"]] = {}
                    d.order.append(r["event_id"])
                d.events[r["event_id"]].setdefault(r["attribute"], []).append(r)
        return d

    def code_attr(self, eid: str) -> str | None:
        return next((a for a in KIND if a in self.events.get(eid, {})), None)

    def first(self, attr: str) -> tuple[str, dict[str, Any]] | None:
        for eid in self.order:
            if attr in self.events[eid]:
                return eid, self.events[eid][attr][0]
        return None


@dataclass
class OracleRoleLLM(MockRoleLLM):
    data: MedicalData | None = None
    profile: str = "staged"
    lines: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)   # (doc_id, 줄 앞부분) → Observation 틀
    _docs: dict[str, _Doc] = field(default_factory=dict)

    # ── 공통 ─────────────────────────────────────────────

    def _d(self, doc: dict[str, Any]) -> _Doc:
        if doc["doc_id"] not in self._docs:
            self._docs[doc["doc_id"]] = _Doc.of(doc)
        return self._docs[doc["doc_id"]]

    def _level(self, node: str, attr: str, coarse: bool, answer_level: str | None) -> str:
        """답할 노드: 기록 노드 또는 그 상위 (단계 공개형의 첫 답)."""
        anc = self.data.anc(node)
        if attr == "PERIOD" and answer_level:
            tag = {"MONTH": "_MONTH_", "YEAR": "_YEAR_", "QUARTER": "_QUARTER_", "DAY": "_DAY_"}[answer_level]
            return next((a for a in anc if tag in a), node)
        if not coarse:
            return node
        if attr == "AGE":
            return next((a for a in anc if a.startswith("AGE10_")), node)
        if attr == "PERIOD":
            return next((a for a in anc if "_YEAR_" in a), node)
        if attr == "REGION":
            return anc[1] if len(anc) > 2 else node
        return node

    def _emit(self, ref: str, doc: dict[str, Any], d: _Doc, attr: str, row: dict[str, Any], node: str, out: list[str]) -> None:
        eid = row.get("event_id") or ""
        if attr in ("SEX", "REGION"):
            prefix = f"{ref} · {'성별' if attr == 'SEX' else '거주지'}"
        else:
            j = d.order.index(eid) + 1
            ca = d.code_attr(eid) or attr
            what = {"AGE": f"{KIND[ca]} 당시 나이", "PERIOD": None}.get(attr, KIND.get(attr, attr))
            if attr == "PERIOD":
                what = f"{KIND[ca]} {'종료일' if '_END_' in node else '시작일'}"
            prefix = f"{ref} · [기록{j}] {what}"
        value = row["span_text"] if node == row["node_id"] and row.get("span_text") else self.data.label(node)   # 기록 그대로면 문서 표기
        line = f"{prefix}: {value}"
        if line in out:
            return
        tmpl = dict(attribute=attr, inference_mode="EXPLICIT", confidence=5, subject="TARGET_PATIENT", context_status="UNSPECIFIED",
                    event_ref=("e_" + eid) if eid else None)
        if attr == "PERIOD":
            tmpl["time_role"] = "_".join(node.split("_")[1:3])
        if attr == "MED":
            tmpl["med_assertion"] = "PRESCRIBED"
        self.lines[(doc["doc_id"], prefix.split(" · ", 1)[1])] = tmpl
        out.append(line)

    # ── 대상 AI ───────────────────────────────────────────

    def _turn0(self, docs: list[dict[str, Any]], intent: dict[str, Any]) -> str:
        out = [f"현재 환자와 비슷한 과거 사례 {len(docs)}건을 찾았습니다."]
        main = intent["binding"]["main_dx_node"]
        for i, doc in enumerate(docs, 1):
            d, ref = self._d(doc), f"사례{i}"
            dx = next(((e, r) for e in d.order for r in d.events[e].get("DX", []) if main in self.data.anc(r["node_id"])), None) or d.first("DX")
            if dx:
                self._emit(ref, doc, d, "DX", dx[1], dx[1]["node_id"], out)
            for a in ITEM_ATTR[intent["qtype"]]:
                it = d.first(a)
                if it:
                    self._emit(ref, doc, d, a, it[1], it[1]["node_id"], out)
                    break
        return "\n".join(out)

    def _anchor(self, d: _Doc, ref: str, intent: dict[str, Any]) -> str | None:
        key = intent.get("key")
        if ref == intent["case_A"] and isinstance(key, tuple):
            for x in key:
                if isinstance(x, str) and ":e_" in x and x.split(":e_", 1)[1] in d.events:
                    return x.split(":e_", 1)[1]
        for g in reversed(intent["events"].get(ref, [])):
            if g.startswith("e_") and g[2:] in d.events:
                return g[2:]
        for a in ITEM_ATTR[intent["qtype"]] + ("DX",):
            f = d.first(a)
            if f:
                return f[0]
        return d.order[0] if d.order else None

    def _answer(self, ref: str, doc: dict[str, Any], attr: str, seed: dict[str, Any], intent: dict[str, Any], out: list[str]) -> None:
        d = self._d(doc)
        said = set(intent["said"].get(ref, []))
        rel = seed.get("expected_relation") or "NEW"
        deeper = rel in ("DESCENDANT", "LINKED_EVENT")
        coarse = self.profile == "staged" and not deeper
        lvl = seed.get("answer_level")
        if attr == "SEX" and d.sex:
            return self._emit(ref, doc, d, "SEX", d.sex, d.sex["node_id"], out)
        if attr == "REGION" and d.region:
            return self._emit(ref, doc, d, "REGION", d.region, self._level(d.region["node_id"], "REGION", coarse, None), out)
        anchor = self._anchor(d, ref, intent)
        if anchor is None:
            return
        if attr in ("AGE", "PERIOD"):
            rows = d.events[anchor].get(attr)
            if attr == "AGE" and not rows:                     # 문서의 나이는 진단 당시 나이만 있다 → 가장 가까운 진단의 나이
                f = d.first("AGE")
                if not f:
                    return
                anchor, rows = f[0], [f[1]]
            if not rows:
                return
            row = next((r for r in rows if "_START_" in r["node_id"]), rows[0]) if attr == "PERIOD" else rows[0]
            return self._emit(ref, doc, d, attr, row, self._level(row["node_id"], attr, coarse, lvl), out)
        # 진단·시술·약·계획
        if deeper:
            active = [n for n in said if self.data.N.get(n, {}).get("attribute") == attr]
            cands = [(e, r) for e in d.order for r in d.events[e].get(attr, []) if any(a in self.data.anc(r["node_id"]) for a in active)]
            pick = next((x for x in cands if x[0] == anchor), None) or (cands[0] if cands else None)
        else:
            mine = d.events[anchor].get(attr, [])
            pick = next(((anchor, r) for r in mine if r["node_id"] not in said), None)
            if pick is None:
                pick = next(((e, r) for e in d.order for r in d.events[e].get(attr, []) if r["node_id"] not in said), None)
        if pick is None:
            pick = d.first(attr)
        if pick:
            self._emit(ref, doc, d, attr, pick[1], pick[1]["node_id"], out)

    def _follow(self, docs: list[dict[str, Any]], intent: dict[str, Any]) -> str:
        seed = intent["seed"]
        refs = [f"사례{i}" for i in range(1, len(docs) + 1)] if seed.get("scope") == "GROUP" else [intent["case_A"]]
        out: list[str] = []
        for ref in refs:
            n = _case_no(ref)
            if not 1 <= n <= len(docs):
                continue
            for attr in [seed["target_qi"]] + ([seed["target_qi_2"]] if seed.get("target_qi_2") else []):
                self._answer(ref, docs[n - 1], attr, seed, intent, out)
        return "\n".join(out) if out else "기록에서 해당 정보를 찾지 못했습니다."

    # ── 역할 ─────────────────────────────────────────────

    def complete(self, role: str, system: str, messages: list[dict[str, str]], **kw: Any) -> str:
        if role == "target":
            self.usage.append(dict(role=role, model=f"oracle-{self.profile}", input_tokens=0, output_tokens=0, latency_ms=0.0, attempts=1, truncated=False))
            intent = kw.get("intent") or {}
            if intent.get("kind") == "RETRIEVAL":
                return self._turn0(kw["docs"], intent)
            return self._follow(kw["docs"], intent)
        if role == "extractor":
            self.usage.append(dict(role=role, model="oracle-extractor", input_tokens=0, output_tokens=0, latency_ms=0.0, attempts=1, truncated=False))
            return json.dumps(self._extract(kw["docs"], kw["response"]), ensure_ascii=False)
        if role == "rewriter":
            self.usage.append(dict(role=role, model="oracle-rewriter", input_tokens=0, output_tokens=0, latency_ms=0.0, attempts=1, truncated=False))
            return self._rewrite(kw["response"], kw["plan"])
        return super().complete(role, system, messages, **kw)

    def _extract(self, docs: list[dict[str, Any]], response: str) -> list[dict[str, Any]]:
        obs = []
        for ln in response.splitlines():
            m = _LINE.match(ln.strip())
            if not m:
                continue
            ref, rest, value = m.group(1), m.group(2), m.group(3).strip()
            n = _case_no(ref)
            if value == SUPPRESSED or not 1 <= n <= len(docs):
                continue
            t = self.lines.get((docs[n - 1]["doc_id"], rest))
            if t is None:
                continue
            obs.append(dict(t, case_ref=ref, raw_value=value, evidence_spans=[value]))
        return obs

    def _rewrite(self, response: str, changes: list[dict[str, Any]]) -> str:
        lines = response.splitlines()
        for c in changes:
            rep = c["to_label"] if c["action"] == "generalize" else SUPPRESSED
            for i, ln in enumerate(lines):
                m = _LINE.match(ln.strip())
                if m and m.group(1) == c["case_ref"] and m.group(3).strip() == c["raw_value"] and self._attr_of(m.group(2)) == c["attribute"]:
                    lines[i] = f"{m.group(1)} · {m.group(2)}: {rep}"
                    break
        return "\n".join(lines)

    @staticmethod
    def _attr_of(rest: str) -> str:
        if rest == "성별":
            return "SEX"
        if rest == "거주지":
            return "REGION"
        if rest.endswith("당시 나이"):
            return "AGE"
        if rest.endswith(("시작일", "종료일")):
            return "PERIOD"
        w = rest.split("] ", 1)[-1]
        return next((a for a, k in KIND.items() if w == k), "?")


# ── 실행기 ─────────────────────────────────────────────────

def plan_all(per_type: int | None, seed: int):
    """질의 환자 풀(QUERY_POOL) 전원을 유형마다 (해당 유형이 될 수 있는 사람만). per_type을 주면 유형마다 그 수만 무작위로."""
    import random
    from medical.data import QUERY_POOL
    from medical.retrieval import QTYPES, query_binding

    def planner(data: MedicalData, split: dict[str, str], cfg) -> list[tuple[str, str, str, str]]:
        rng = random.Random(seed)
        pool = sorted(p for p, s in split.items() if s == QUERY_POOL)
        plan = []
        for qt in QTYPES:
            elig = [p for p in pool if query_binding(data, p, qt, random.Random(0))]
            pick = sorted(rng.sample(elig, per_type)) if per_type and per_type < len(elig) else elig
            plan += [(p, qt, "DOCTOR") for p in pick]
        return [(f"T{i:04d}", p, qt, role) for i, (p, qt, role) in enumerate(plan, 1)]
    return planner


def main(argv: list[str] | None = None) -> int:
    import argparse
    from pathlib import Path
    from medical.config import MedicalConfig
    from medical.experiment import run_experiment

    ap = argparse.ArgumentParser(prog="python -m medical.simulate")
    ap.add_argument("--out", required=True)
    ap.add_argument("--profile", choices=["staged", "full"], default="staged")
    ap.add_argument("--fuzzer", choices=["uniform", "feedback"], default="uniform")
    ap.add_argument("--arms", default="C0,C1,C1S")
    ap.add_argument("--per-type", type=int, default=None, help="유형마다 질의 환자 수 (기본: 풀 전원)")
    ap.add_argument("--mode", choices=["efficiency", "exploration"], default="efficiency")
    ap.add_argument("--budget", type=int, default=10)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    data = MedicalData()
    cfg = MedicalConfig(arms=tuple(x for x in a.arms.split(",") if x), fuzzer=a.fuzzer, mode=a.mode, budget_B=a.budget)
    llm = OracleRoleLLM(data=data, profile=a.profile)
    out = Path(a.out)
    run_experiment(cfg, llm, out, data=data, planner=plan_all(a.per_type, cfg.seed),
                   progress=(lambda s: None) if a.quiet else print)
    meta = json.loads((out / "run_meta.json").read_text(encoding="utf-8"))
    meta["simulation"] = dict(target=f"oracle-{a.profile}", extractor="oracle (오류 0)", rewriter="oracle (정확 적용)",
                              mutator="Seed 문장 그대로", fuzzer=a.fuzzer)
    (out / "run_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
