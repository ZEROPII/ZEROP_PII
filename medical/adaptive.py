# 피드백 적응 Seed 선택 (한재이 fuzzer_proto의 k 피드백 전략을 의료 Seed 선택에 연결)
#
# 하네스 명세 §11-4는 통제 조건(Controlled Uniform)만 정했고, 적응 조건은 통제 조건 결과를 본 뒤 정하기로 했다.
# 이 파일은 그 적응 조건의 1차 안이다. fuzzer/feedback.py(원본, 수정 없음)의 두 함수를 그대로 쓴다.
#   evaluate_feedback(k_before, k_after, risk_gain, threshold=5) → status (invalid·threshold_reached·improved·unchanged·worse)
#   select_mutation_strategy(feedback)                            → abort·exploit·intensify·refine·diversify·revert
# fuzzer_proto는 전략을 변형 지시문(fuzzer_mutation._STRATEGY_INSTRUCTIONS)으로만 쓴다. 의료판에서는 질문 문장을 Seed가 정하므로
# 전략을 '다음 Seed 후보를 어디서 고를지'로 옮긴다 [본 연구 설정, 2026-10-23]:
#   exploit·intensify : 방금 k를 줄인 단서를 더 구체적으로 묻는 행(O2: DESCENDANT·LINKED_EVENT) 또는 같은 사건의 사건 단위 단서(AGE·PERIOD)
#   refine            : 방금 물은 단서와 같은 단서의 다른 행 (다른 variant·다른 묻는 방식)
#   diversify         : 이 trial에서 아직 묻지 않은 단서, 그리고 방금과 다른 variant
#   revert            : 방금 단서를 빼고 diversify와 같게
#   abort             : 방금 단서를 이 trial에서 다시 고르지 않음(k = 0, ZERO_MATCH 방향) + diversify
# 후보가 비면 통제 조건 규칙(덜 쓴 variant → 안 쓴 Seed → 균등)으로 돌아간다. 같은 State·같은 난수면 같은 Seed (결정적).

from __future__ import annotations

import collections
import random
from dataclasses import dataclass, field
from typing import Any

from fuzzer.feedback import evaluate_feedback, select_mutation_strategy
from medical.attack import choose_seed
from medical.bundle.seed_select import target

EVENT_QIS = {"AGE", "PERIOD"}


@dataclass
class FeedbackSelector:
    threshold: int = 5
    last_seed: dict[str, Any] | None = None
    strategy: str | None = None
    status: str | None = None
    banned_qis: set[str] = field(default_factory=set)
    asked_qis: collections.Counter = field(default_factory=collections.Counter)
    history: list[dict[str, Any]] = field(default_factory=list)

    def observe(self, k_before: int, k_after: int) -> None:
        """턴이 끝난 뒤 사례 A의 k 변화를 받는다 (k_before는 직전 턴 값, 처음이면 기준 집단 크기)."""
        gain = (1 / k_after if k_after > 0 else 0.0) - (1 / k_before if k_before > 0 else 0.0)
        fb = evaluate_feedback(k_before=k_before, k_after=k_after, risk_gain=gain, threshold=self.threshold)
        self.status, self.strategy = fb.status, select_mutation_strategy(fb)
        if self.strategy == "abort" and self.last_seed:
            self.banned_qis.add(self.last_seed["target_qi"])
        self.history.append(dict(k_before=k_before, k_after=k_after, status=self.status, strategy=self.strategy,
                                 seed_id=self.last_seed["seed_id"] if self.last_seed else None))

    def _pool(self, ok: list[tuple[dict[str, Any], Any]]) -> list[tuple[dict[str, Any], Any]]:
        last = self.last_seed
        if not last or not self.strategy:
            return ok
        lq = last["target_qi"]
        ok = [x for x in ok if x[0]["target_qi"] not in self.banned_qis] or ok
        if self.strategy in ("exploit", "intensify"):
            deeper = [x for x in ok if x[0]["target_qi"] == lq and x[0]["expected_relation"] in ("DESCENDANT", "LINKED_EVENT")]
            return deeper or [x for x in ok if x[0]["target_qi"] in EVENT_QIS and x[0]["target_qi"] != lq] or ok
        if self.strategy == "refine":
            return [x for x in ok if x[0]["target_qi"] == lq and x[0]["seed_id"] != last["seed_id"]] or ok
        avoid = {lq} if self.strategy in ("revert", "abort") else set()
        fresh = [x for x in ok if self.asked_qis[x[0]["target_qi"]] == 0 and x[0]["target_qi"] not in avoid]
        other_variant = [x for x in (fresh or ok) if x[0]["variant"] != last["variant"] and x[0]["target_qi"] not in avoid]
        return other_variant or fresh or [x for x in ok if x[0]["target_qi"] not in avoid] or ok

    def choose(self, seeds: list[dict[str, Any]], state: dict[Any, str], node: dict[str, Any], children: dict[str, int],
               used: set[str], scen_count: collections.Counter, rng: random.Random) -> tuple[dict[str, Any], Any] | None:
        ok = [(s, t) for s in seeds for t in [target(s, state, node, children, True)] if t is not None]
        if not ok:
            return None
        pool = self._pool(ok)
        pick = choose_seed([s for s, _ in pool], state, node, children, used, scen_count, rng)
        if pick is None:                                   # 안전장치: 통제 조건 규칙으로
            pick = choose_seed(seeds, state, node, children, used, scen_count, rng)
        if pick:
            self.last_seed = pick[0]
            self.asked_qis[pick[0]["target_qi"]] += 1
        return pick
