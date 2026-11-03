"""
추출 관찰 바로잡기 [본 연구 설정, 2026-11-03] — LLM 추출기가 낸 Observation의 단서 종류 · 묶음 표기를 고친다.

holdout_1 기록에서 본 오류 유형이다. 값은 바꾸지 않고, 바꾼 관찰에는 fixed_from에 원래 종류를 남긴다.
1. 약을 다른 종류로 표시: 'ibuprofen 100 MG Oral Tablet'을 관리 계획(PLAN) · 시술 · 진단으로 뽑음 → 약(MED)
   (용량 단위 MG · ML 등이나 제형 Oral · Tablet · Injection 등이 있으면 약 이름으로 본다)
2. 나이를 날짜로 표시: PERIOD인데 값이 '3세', '1-2세' → 나이(AGE). '12세 이후'처럼 시점이 아닌 말은 건드리지 않는다.
3. 나이 두 개를 화살표로 묶음: '37세→43세' → '37세', '43세' 두 관찰 (두 시점의 나이가 모두 드러남)
4. 여러 항목을 쉼표로 묶음: 'acetaminophen 325 MG Oral Tablet, Respiratory therapy'를 관리 계획 하나로 뽑음
   → 항목마다 나눠, 약 이름은 약으로, 나머지는 원래 종류로 둔다. 진단명 자체에 쉼표가 있는 경우
   ('Chronic sinusitis, unspecified')를 깨지 않도록, 약 이름이 하나 이상 섞였을 때만 나눈다
   (원래 종류가 약이면 약 이름이 둘 이상일 때만).
"""
from __future__ import annotations

import re
from typing import Any

_DRUG = re.compile(r"\b\d+(?:\.\d+)?\s*(?:MG|MCG|ML|UNT|MEQ|MG/ML|MG/MG|%)(?![A-Za-z])"
                   r"|\b(?:Oral|Tablet|Capsule|Injection|Injectable|Suspension|Inhaler|Inhalation|Syringe|Transdermal)\b",
                   re.IGNORECASE)
_AGE_ONLY = re.compile(r"(?:만\s*)?\d{1,3}(?:\s*[-~]\s*\d{1,3})?\s*(?:세|살)")
_AGE_ARROW = re.compile(r"(\d{1,3})\s*(?:세|살)?\s*(?:→|->|⇒)\s*(\d{1,3})\s*(?:세|살)")


def _split_list(o: dict[str, Any], att: str, raw: str) -> list[dict[str, Any]] | None:
    parts = [p.strip() for p in re.split(r"\s*,\s*", raw) if p.strip()]
    drugs = [p for p in parts if _DRUG.search(p)]
    if len(parts) < 2 or not drugs or (att == "MED" and len(drugs) < 2):
        return None
    return [dict(o, attribute="MED" if _DRUG.search(p) else att, raw_value=p, fixed_from=f"{att}_LIST") for p in parts]


def fix_observations(obs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for o in obs:
        att, raw = o.get("attribute"), str(o.get("raw_value") or "").strip()
        parts = _split_list(o, att, raw) if att in ("PLAN", "PROC", "DX", "MED") and "," in raw else None
        if parts:
            out += parts
        elif att in ("PLAN", "PROC", "DX") and _DRUG.search(raw):
            out.append(dict(o, attribute="MED", fixed_from=att))
        elif att == "PERIOD" and _AGE_ONLY.fullmatch(raw):
            o2 = {k: v for k, v in o.items() if k != "time_role"}
            out.append(dict(o2, attribute="AGE", fixed_from=att))
        elif att == "AGE" and _AGE_ARROW.search(raw):
            m = _AGE_ARROW.search(raw)
            for a in (m.group(1), m.group(2)):
                out.append(dict(o, raw_value=f"{a}세", fixed_from="AGE_ARROW"))
        else:
            out.append(o)
    return out
