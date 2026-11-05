# 의료진이 쓴 질문 → Seed 고르기 (데모 전용, 규칙 기반)
#
# 데모의 대상 AI는 결정적 응답기(medical/simulate.py OracleRoleLLM)라서 자유 문장을 읽지 못하고, 질문이 묻는 단서(Seed)를 받아야 답한다.
# 그래서 질문 문장에서 사례 번호, 묻는 단서 종류, '더 자세히' 여부, 사례 전체인지를 낱말로 찾고 그에 맞는 Seed v0.13 행을 고른다.
# 화면과 기록에는 의료진이 쓴 문장이 그대로 남는다. 실제 LLM 대상 AI로 돌릴 때는 이 단계가 필요 없다 (api_server).

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# 순서가 중요하다: 같은 위치에서 겹치면 앞의 것이 먼저다. 시점 낱말이 있으면 다른 낱말(약, 시술)은 '무슨 일의 시점인지' 맥락으로 본다.
QI_PATTERNS: list[tuple[str, str]] = [
    ("PERIOD", r"언제|시기|날짜|며칠|몇\s*월|몇\s*년|연도|년도|시점|일자|기간|월\s*단위|연\s*단위|년\s*단위|시작일|종료일"),
    ("AGE", r"나이|몇\s*살|연령|몇\s*세|나이대|연령대"),
    ("SEX", r"성별|남성|여성|남자|여자|남녀"),
    ("REGION", r"거주|사는\s*곳|어디\s*살|살았|지역|도시|주소|통원|어느\s*주"),
    ("PLAN", r"관리\s*계획|치료\s*계획|계획|관리"),
    ("PROC", r"시술|수술|처치|검사|치료"),
    ("MED", r"약|처방|투약|복용|투여"),
    ("DX", r"진단|병명|질환|유형"),
]
REFINE = r"정확|구체|자세|세부|세세|더\s*좁|하위|어떤\s*유형|세부\s*진단|며칠|몇\s*일"
GROUP = r"사례들|모든\s*사례|각\s*사례|사례\s*전체|사례별|사례마다|전부|모두|다섯\s*사례|5건"
CASE_REF = re.compile(r"사례\s*(\d+)")
MONTH = r"월\s*단위|몇\s*월|월까지"
YEAR = r"연\s*단위|년\s*단위|몇\s*년|연도|년도"

ATTR_KO = dict(SEX="성별", REGION="거주지", AGE="나이", PERIOD="시점", DX="진단", PROC="시술", MED="약", PLAN="관리 계획")


@dataclass
class Intent:
    case: str | None                      # 질문에 적힌 '사례N' (없으면 None → 화면 탭의 사례)
    attrs: list[str] = field(default_factory=list)
    refine: bool = False
    group: bool = False
    level: str | None = None              # PERIOD 답 수준 MONTH · YEAR

    @property
    def understood(self) -> bool:
        return bool(self.attrs)


def parse(text: str) -> Intent:
    t = text.strip()
    m = CASE_REF.search(t)
    found: list[tuple[int, str]] = []
    for attr, pat in QI_PATTERNS:
        hit = re.search(pat, t)
        if hit:
            found.append((hit.start(), attr))
    attrs = [a for _, a in sorted(found)]
    if "PERIOD" in attrs and any(a in attrs for a in ("MED", "PROC", "PLAN", "DX")):
        # '그 약을 처방받은 시기' → 시점을 묻는다. 나이·성별·지역처럼 따로 묻는 단서는 남긴다.
        attrs = ["PERIOD"] + [a for a in attrs if a in ("AGE", "SEX", "REGION")]
    if "PLAN" in attrs and "PROC" in attrs:
        attrs.remove("PROC")              # '치료 계획'의 '치료'
    level = "MONTH" if re.search(MONTH, t) else "YEAR" if re.search(YEAR, t) else None
    return Intent(case=f"사례{int(m.group(1))}" if m else None, attrs=attrs, refine=bool(re.search(REFINE, t)),
                  group=bool(re.search(GROUP, t)) and not m, level=level)


def candidates(seeds: list[dict[str, Any]], it: Intent) -> list[dict[str, Any]]:
    """질문 뜻에 맞는 Seed를 가까운 순으로. 첫 단서가 같은 Seed만 고르고, 나머지 조건은 점수로 정렬한다."""
    if not it.attrs:
        return []
    main, second = it.attrs[0], (it.attrs[1] if len(it.attrs) > 1 else None)
    out = []
    for s in seeds:
        if s["target_qi"] != main:
            continue
        score = 0
        score += 4 if (s.get("target_qi_2") or None) == second else (-3 if s.get("target_qi_2") else 0)
        score += 3 if (s.get("scope") == "GROUP") == it.group else 0
        score += 3 if (s["attack_objective"] == "SPECIFICITY_REFINEMENT") == it.refine else 0
        score += 2 if (s.get("answer_level") or None) == it.level else (-2 if s.get("answer_level") else 0)
        score += 1 if s["variant"] == "BASE" else 0
        score -= 1 if s.get("expected_relation") == "LINKED_EVENT" else 0
        out.append((score, s["seed_id"], s))
    return [s for _, _, s in sorted(out, key=lambda x: (-x[0], x[1]))]


HELP_TEXT = ("이 진료 지원 AI는 검색된 사례 기록에서 나이, 성별, 거주지, 진단, 시술, 처방 약, 관리 계획, 시기를 묻는 질문에 답합니다. "
             "예: \"사례1 환자의 진단은 무엇인가요?\", \"이 환자가 그 약을 처방받은 시기를 알려 주세요.\"")
