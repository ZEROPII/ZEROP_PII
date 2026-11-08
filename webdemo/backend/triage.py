# 환자 위험 등급 (ADR-0041): 외래 목록 · 차트 머리에 보이는 다섯 단계 참고 등급. 응급실 분류(KTAS)처럼 색으로 나누지만,
# 응급도가 아니라 EMR 기록(마지막 내원 기준)으로 센 진료 위험이다. LLM을 쓰지 않고 정해 둔 규칙으로만 정한다.
#
#   1 위급  진행 중인 위급 진단 (패혈증 · 쇼크 · 급성 호흡곤란 · 심근경색 · 뇌졸중 · 폐색전 · 심정지)
#   2 높음  진행 중인 중증 진단 (악성 종양 · 심부전 · 만성 신장병 4~5기 · 폐기종/COPD · HIV · 치매 · 간경화), 또는 점수 7점 이상
#   3 주의  점수 3점 이상
#   4 낮음  점수 1점 이상
#   5 안정  점수 0점 (진행 중인 진단 · 처방이 없거나 가벼운 것뿐)
#
# 점수: 진행 중인 진단마다 무게(위급 5 · 중증 4 · 주요 만성 2 · 만성 1 · 가벼움 0, 만성 질환 합은 6점까지)
#       + 처방 중인 약(5종 이상 2, 3~4종 1) + 나이(80세 이상 2, 65세 이상 1, 2세 미만 1).
#       당뇨 합병증처럼 한 병이 진단 여러 줄로 남아도 만성 질환만으로는 2등급(높음)을 넘지 않게 합을 묶는다. 진행 중 판단은 차트와 같다 (emr.record: 오래된 급성 · 처방은 빼고 셈).
# 화면에는 등급과 까닭 세 줄까지를 보이고, '기록 기반 참고 등급이며 임상 판단을 대신하지 않는다'고 같이 적는다.

from __future__ import annotations

import re
from typing import Any

LEVELS = {1: "위급", 2: "높음", 3: "주의", 4: "낮음", 5: "안정"}
CRITICAL = re.compile(r"\b(sepsis|septic|shock|acute respiratory distress|respiratory failure|myocardial infarction|nstemi|stemi|"
                      r"stroke|cerebral infarction|cerebrovascular accident|pulmonary embolism|cardiac arrest)\b", re.I)
SEVERE = re.compile(r"\b(malignant|carcinoma(?! in situ)|cancer|myeloma|leukemia|leukaemia|lymphoma|metasta\w*|heart failure|"
                    r"chronic kidney disease,? stage [45]|end[- ]stage renal|dialysis|emphysema|chronic obstructive|copd|"
                    r"human immunodeficiency virus|hiv|acquired immune deficiency|aids|alzheimer|dementia|cirrhosis)\b", re.I)
MAJOR = re.compile(r"\b(diabet\w*|ischemic heart|coronary|chronic kidney disease|atrial fibrillation|valve|stenosis|regurgitation|"
                   r"epilepsy|asthma|carcinoma in situ|neoplasm|opioid|substance|alcohol\w* (?:abuse|dependence)|osteoporosis)\b", re.I)
MODERATE = re.compile(r"\b(hypertension|hyperlipidemia|hypertriglyceridemia|hypercholesterol\w*|metabolic syndrome|prediabetes|"
                      r"hyperglycemia|anemia|obesity|sleep apnea|migraine|osteoarthritis|arthritis|gout|polyp|fibromyalgia|scoliosis)\b", re.I)


def weight(label: str) -> int:
    """진행 중인 진단 하나의 무게."""
    if CRITICAL.search(label):
        return 5
    if SEVERE.search(label):
        return 4
    if MAJOR.search(label):
        return 2
    if MODERATE.search(label):
        return 1
    return 0


def _names(xs: list[str], n: int = 2) -> str:
    head = ", ".join(xs[:n])
    return head + (f" 외 {len(xs) - n}개" if len(xs) > n else "")


def assess(groups: dict[str, dict[str, dict[str, Any]]], *, age: int | None = None, dormant: bool = False) -> dict[str, Any]:
    """
    groups: emr.Emr.record()의 groups (종류 → 이름 → 줄, active 포함). age: 마지막 내원 때 나이.
    돌려주는 것: level(1~5) · label · score · reasons(화면에 보일 까닭, 많아야 셋).
    """
    probs = [g["label"] for g in (groups.get("problems") or {}).values() if g.get("active")]
    meds = [g["label"] for g in (groups.get("medications") or {}).values() if g.get("active")]
    w = {p: weight(p) for p in probs}
    critical = [p for p in probs if w[p] == 5]
    severe = [p for p in probs if w[p] == 4]
    chronic = [p for p in probs if w[p] in (1, 2)]
    score = sum(w[p] for p in critical + severe) + min(6, sum(w[p] for p in chronic))
    poly = 2 if len(meds) >= 5 else 1 if len(meds) >= 3 else 0
    score += poly
    if age is not None:
        score += 2 if age >= 80 else 1 if age >= 65 else 1 if age < 2 else 0
    if critical:
        level = 1
    elif severe or score >= 7:
        level = 2
    elif score >= 3:
        level = 3
    elif score >= 1:
        level = 4
    else:
        level = 5
    reasons: list[str] = []
    if critical:
        reasons.append(f"위급 진단 진행 중: {_names(critical)}")
    if severe:
        reasons.append(f"중증 진단 진행 중: {_names(severe)}")
    if chronic:
        reasons.append(f"만성 질환 {len(chronic)}개 진행 중: {_names(sorted(chronic, key=lambda p: -w[p]))}")
    if poly:
        reasons.append(f"처방 중인 약 {len(meds)}종")
    if age is not None and (age >= 65 or age < 2):
        reasons.append("80세 이상" if age >= 80 else "65세 이상" if age >= 65 else "2세 미만")
    if not reasons:
        reasons.append("진행 중인 주요 진단 · 처방 없음" if not probs else f"가벼운 진단만 진행 중: {_names(probs)}")
    reasons = reasons[:3]
    if dormant:
        reasons.append("장기 미내원: 마지막 내원 때 기록으로 셈")
    return dict(level=level, label=LEVELS[level], score=score, reasons=reasons)
