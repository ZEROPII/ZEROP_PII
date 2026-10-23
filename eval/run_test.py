# run_test.py 상단 코드 수정안
from __future__ import annotations

import json
from pathlib import Path

# evaluation 패키지 내부의 모듈들을 상대 경로로 안전하게 임포트
from .loader import load_population, DEFAULT_PROFILES_PATH, DEFAULT_NODE_PATH
from .schema import PrivacyState, QIObservation
from .risk import evaluate_projected_risk
from .defender import defend_candidate_qis
from .log_schema import CueLabel, ExperimentLogger, TrialRecord, TurnRecord, load_docs, load_trials, load_turns
from .eval_baseline import EvalConfig, Evaluator, to_markdown
OUTPUT_DIR = Path("./evaluation/test_outputs")

def run_simulation():
    print("1. Synthea 576명 데이터셋 로딩...")
    population = load_population(DEFAULT_PROFILES_PATH, DEFAULT_NODE_PATH)
    print(f"   총 {len(population)}명의 환자 레코드가 성공적으로 로드되었습니다.")

    logger = ExperimentLogger(OUTPUT_DIR)
    logger.reset()

    # RAG 더미 문서 생성
    docs_data = [
        {"doc_id": "doc001", "icd3": "E11", "cue_types": ["DX", "MED"]},
        {"doc_id": "doc002", "icd3": "I10", "cue_types": ["DX", "PROC"]},
    ]
    with (OUTPUT_DIR / "RAG문서.jsonl").open("w", encoding="utf-8") as f:
        for d in docs_data:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

    target_icd3_map = {}
    conditions = ["C0", "C1"]  # C0: 무방어, C1: Adaptive Defender 방어 적용

    print("2. 턴 기반 시뮬레이션 및 파이프라인 수행...")
    # 상위 10명 대상 테스트
    for target_idx, target in enumerate(population[:10]):
        target_id = target.person_id
        target_icd3_map[target_id] = "E11"

        for cond in conditions:
            trial_id = f"{target_id}-{cond}-MAIN"
            state = PrivacyState(target_id=target_id, session_id=trial_id)
            turns_logged = []

            # QI 공개 관찰 시뮬레이션
            sample_qis = [
                ("SEX", target.qis.get("SEX")),
                ("DX", target.qis.get("DX")),
                ("MED", target.qis.get("MED")),
            ]

            turn_num = 1
            for qi_type, val in sample_qis:
                if val is None:
                    continue

                obs = QIObservation(qi_type=qi_type, value=val, source_turn=turn_num)
                
                # Risk 평가
                projected = evaluate_projected_risk(population, state, [obs], threshold=5)

                # Defender 방어 동작 결정 (C1일 때만 적용)
                if cond == "C1":
                    decision = defend_candidate_qis(population, state, [obs], generalize_threshold=5, suppress_threshold=3)
                    state = decision.final_state
                    k_final = decision.final_k
                    release_mode = "LLM_REWRITE" if decision.action in ("generalize", "suppress") else "ORIGINAL"
                else:
                    state = projected.state_after
                    k_final = projected.k_after
                    release_mode = "ORIGINAL"

                utility = 1.0 if release_mode == "ORIGINAL" else 0.7

                rec = TurnRecord(
                    trial_id=trial_id,
                    target_id=target_id,
                    condition=cond,
                    turn=turn_num,
                    question_type=qi_type if qi_type in ("MED", "DX", "PROC") else "MED",
                    retrieved_doc_ids=["doc001", "doc002"],
                    release_mode=release_mode,
                    utility=utility,
                    k_val=k_final,
                    case_k_val={"A": k_final},
                    cue_labels=[CueLabel(case_id="A", qi_type=qi_type, label="CORRECT")],
                    answered_cue_types=[qi_type],
                )
                logger.log_turn(rec)
                turns_logged.append(rec)
                turn_num += 1

            logger.add_trial(
                TrialRecord(
                    trial_id=trial_id,
                    target_id=target_id,
                    condition=cond,
                    n_turns=len(turns_logged),
                    mean_utility=sum(t.utility for t in turns_logged) / len(turns_logged) if turns_logged else 0.0,
                )
            )

    logger.flush_trials()
    (OUTPUT_DIR / "target_icd3.json").write_text(json.dumps(target_icd3_map, ensure_ascii=False), encoding="utf-8")
    print(f"   로그 저장 완료: {OUTPUT_DIR}")

def run_evaluation():
    print("3. 자동 평가기(Evaluator) 파이프라인 실행...")
    trials = load_trials(OUTPUT_DIR / "trial요약.json")
    turns = load_turns(OUTPUT_DIR / "턴기록.jsonl", trials)
    docs = load_docs(OUTPUT_DIR / "RAG문서.jsonl")
    target_icd = json.loads((OUTPUT_DIR / "target_icd3.json").read_text(encoding="utf-8"))

    evaluator = Evaluator(turns, trials, docs, EvalConfig(k_req=5))
    evaluator.set_target_icd3(target_icd)
    
    report = evaluator.run()
    md_output = to_markdown(report)
    
    print("\n" + md_output)
    (OUTPUT_DIR / "eval_report.md").write_text(md_output, encoding="utf-8")
    print(f"   최종 평가 리포트 저장 완료: {OUTPUT_DIR / 'eval_report.md'}")

if __name__ == "__main__":
    run_simulation()
    run_evaluation()
