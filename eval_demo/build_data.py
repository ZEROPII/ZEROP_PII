"""poc_summary.json -> data.js 변환 스크립트.

사용법 (저장소 루트에서):
    python scripts/build_data.py                       # data/poc_summary.json 사용
    python scripts/build_data.py path/to/new_summary.json

PPT에만 있고 JSON에는 없는 값(SynthPAI 정보 유지율, 처리 시간 등)은
아래 STATIC 딕셔너리에서 직접 수정하세요.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
src = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "poc_summary.json"
raw = json.loads(src.read_text(encoding="utf-8"))

# ── JSON에 없는 값: 발표자료(37·39·42p) 기준. 새로 측정하면 여기만 고치면 됩니다. ──
STATIC = {
    "infoRetention": {"ours": 44.5, "single": 25.6, "fixed": 2.3,
                      "source": "SynthPAI 30명 · 실제 LLM · 위반 0% 조건 (발표 39p)"},
    "normalPass": {"value": 98.9, "source": "SynthPAI 정상 질문 6턴 · 30만 명 기준 (발표 37p)"},
    "latency": {"meanSec": 0.011, "p95Sec": 0.037,
                "source": "시뮬레이션 · k 계산 + 판정, LLM 제외 (발표 42p)"},
    # 아직 측정 전인 값은 None 으로 두면 화면에 '측정 전'으로 표시됩니다.
    "extraction": {"recall": None, "precision": None, "f1": None,
                   "target": {"recall": 95, "precision": 90, "f1": 0.92}},
}

ARM_KEYS = ["C0", "C1S", "C1"]


def slim_arm(a):
    return {
        "n": a["n"],
        "outcomes": a["outcomes"],
        "violTurn7": a["violation_A_by_turn7"],
        "violFinal": a["violation_A_val"],
        "riskAtTurn0": a["risk_at_turn0"],
        "firstViolationMedian": a["first_violation_turn_median"],
        "cum": a["cumulative_violation_by_turn"],
        "kMed": a["kA_median_by_turn"],
        "utility": a["mean_utility"],
        "release": a["release_modes"],
        "overblock": a["case_level_overblock"],
        "residualFinalK": a.get("residual_violation_final_k", {}),
    }


scenarios = {}
for key, sc in raw.items():
    if key.startswith("fuzzer_compare") or "arms" not in sc:
        continue
    scenarios[key] = {
        "config": sc["config"],
        "arms": {k: slim_arm(sc["arms"][k]) for k in ARM_KEYS if k in sc["arms"]},
    }

fuzzer_compare = {
    "staged": raw.get("fuzzer_compare_staged", {}).get("C0"),
    "full": raw.get("fuzzer_compare_full", {}).get("C0"),
}

data = {
    "meta": {"title": "비식별화 성능 평가 대시보드", "updated": "2026-10-29",
             "source": "poc_summary.json"},
    "scenarioLabels": {"staged": "staged", "full": "full"},
    "fuzzerLabels": {"uniform": "무작위", "feedback": "k 피드백"},
    "armLabels": {"C0": "방어 없음", "C1S": "단일 응답 가드레일", "C1": "누적 가드레일 (Ours)"},
    "scenarios": scenarios,
    "fuzzerCompare": fuzzer_compare,
    "static": STATIC,
}

out = ROOT / "data.js"
out.write_text("window.DASH = " + json.dumps(data, ensure_ascii=False, indent=1) + ";\n",
               encoding="utf-8")
print(f"wrote {out} ({out.stat().st_size:,} bytes)")
