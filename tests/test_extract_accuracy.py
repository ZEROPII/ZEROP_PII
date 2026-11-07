# medical.extract_accuracy: 결정적 응답기 실행은 추출기가 응답기 줄 형식을 그대로 읽으므로 재현율·정밀도가 100%여야 한다.
from pathlib import Path

from medical.config import MedicalConfig
from medical.data import MedicalData
from medical.experiment import run_experiment
from medical.extract_accuracy import measure, report, segments
from medical.simulate import OracleRoleLLM, plan_all


def test_segments_grouped_cases():
    seg = segments("사례1, 2, 3: 모두 남성 환자입니다. 사례4는 여성입니다.")
    assert set(seg) == {1, 2, 3, 4} and "남성" in seg[2] and "여성" in seg[4] and "여성" not in seg[1]


def test_oracle_run_scores_full(tmp_path: Path):
    data = MedicalData()
    cfg = MedicalConfig(mode="exploration", budget_B=4)
    out = tmp_path / "run"
    run_experiment(cfg, OracleRoleLLM(data=data, profile="full"), out, data=data, planner=plan_all(1, cfg.seed), progress=lambda s: None)
    res = measure(out, data=data)
    total = next(r for r in res["rows"] if r["attribute"] == "ALL")
    assert total["gt"] > 0 and total["recall_answer"] == 1.0 and total["recall_conversation"] == 1.0
    assert total["precision"] == 1.0 and total["wrong"] == 0
    assert "| 전체 |" in report(res)
