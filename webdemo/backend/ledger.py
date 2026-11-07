# 과거 환자 단위 공개 원장 (ADR-0032, 연구자 4인 검토 P0-1)
#
# 지금까지 누적 판정(C1)의 State는 대화 하나 안에서만 쌓였다. 같은 과거 환자를 새 대화로 다시 열거나 다른 의사 계정으로 물으면
# 이미 나간 단서가 새 단서로 다시 세어졌다 (통합 체험 2026-11-05 이슈 2: doctor2가 같은 환자를 열자 'Respiratory therapy'가
# 새 단서로 다시 추가됨). 각각은 통과하는 단서를 대화를 나눠 모으면 막을 수 없다.
#
# 원장은 의료진 대화(source='clinic')의 화면 갈래(C1)가 실제로 내보낸 단서를 과거 환자(STORE patient_id)마다 적는다.
#   - 적는 것   : 턴마다 그 사례의 누적 State에 새로 들어간 값(내보낸 답을 다시 추출한 값)과 보안 담당자가 승인해 공개한 값.
#                 대화 · 계정 · 시각 · 종류(turn · approval)를 같이 둔다. 값의 글자(원문)는 두지 않고 온톨로지 노드만 둔다.
#   - 읽는 것   : 대화가 사례를 판정할 때, 같은 과거 환자에 대해 기간 창(기본 90일) 안에 다른 대화들에서 나간 값.
#                 이 값을 그 사례의 누적 State 앞에 붙여 판정한다 (review.RuledArmRun._basis). 그래서 대화를 나누거나 계정을 바꿔도
#                 같은 과거 환자의 후보 수는 앞서 나간 단서까지 합쳐 센다 (의사끼리 맞춰 보는 결합도 같은 셈).
#   - 사건 묶음 : 추출기의 사건 표지('e1')는 대화 안에서만 뜻이 있다. 다른 대화의 값은 '사례N:대화번호:표지'로 묶어 대화끼리 섞지 않는다.
#                 같은 대화의 같은 사건은 지금처럼 한 사건이 함께 만족해야 후보다.
# 연구 하네스(medical/)와 레드팀 · 비교 갈래(C0 · C1S)는 원장을 쓰지 않는다. 운영 모드는 DB(disclosure_ledger 표)에 남겨
# 서버를 다시 켜도 이어 쓰고, 데모 모드는 메모리에만 둔다.

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Iterable

DAY = 86400.0
DEFAULT_WINDOW_DAYS = 90.0
KINDS = ("turn", "approval")


def event_label(group: str | None) -> str | None:
    """State의 사건 묶음 이름에서 대화 안 표지만 ('사례3:e1' → 'e1'). 사례 번호는 대화마다 달라 뗀다."""
    if not group:
        return None
    return group.split(":", 1)[1] if ":" in group else group


class DisclosureLedger:
    """
    store가 있으면 DB에 쓰고, 켤 때 기간 창 안의 기록을 메모리로 올린다. window_days <= 0이면 기간 제한 없이 모두 센다.
    version은 기록이 늘 때마다 1씩 올라간다 (대화가 앞선 원장 값을 다시 읽을지 정하는 데 쓴다).
    """

    def __init__(self, store: Any = None, *, window_days: float = DEFAULT_WINDOW_DAYS, clock: Callable[[], float] = time.time) -> None:
        self.store = store
        self.window_days = float(window_days)
        self.window = max(self.window_days, 0.0) * DAY
        self.clock = clock
        self.lock = threading.RLock()
        self._by_pat: dict[str, list[dict[str, Any]]] = {}
        self.version = 0
        if store is not None:
            for r in store.ledger_entries(self._since()):
                self._by_pat.setdefault(r["patient_id"], []).append(r)

    def _since(self, now: float | None = None) -> float | None:
        if not self.window:
            return None
        return (self.clock() if now is None else now) - self.window

    # ── 쓰기 ──
    def record(self, patient_id: str, items: Iterable[dict[str, Any]], *, conv_id: str, user_id: int | None = None,
               kind: str = "turn", turn: int | None = None, at: float | None = None) -> int:
        """State에 새로 들어간 값(kcalc 입력 모양)을 적는다. 적은 수를 돌려준다."""
        if kind not in KINDS:
            raise ValueError(kind)
        now = self.clock() if at is None else at
        rows = [dict(patient_id=patient_id, conv_id=conv_id, user_id=user_id, at=now, kind=kind, turn=turn,
                     attribute=d["attribute"], node_id=d["node_id"], event_label=event_label(d.get("event_group")))
                for d in items if d.get("attribute") and d.get("node_id")]
        if not rows:
            return 0
        with self.lock:
            if self.store is not None:
                self.store.add_ledger(rows)
            self._by_pat.setdefault(patient_id, []).extend(rows)
            self.version += 1
        return len(rows)

    def set_user(self, conv_id: str, user_id: int | None) -> None:
        """대화를 만든 뒤에 계정이 정해진 기록(첫 답)의 계정을 채운다."""
        if user_id is None:
            return
        with self.lock:
            hit = False
            for rows in self._by_pat.values():
                for r in rows:
                    if r["conv_id"] == conv_id and r["user_id"] is None:
                        r["user_id"] = user_id
                        hit = True
            if hit and self.store is not None:
                self.store.set_ledger_user(conv_id, user_id)

    # ── 읽기 ──
    def entries(self, patient_id: str, *, exclude_conv: str | None = None, now: float | None = None) -> list[dict[str, Any]]:
        since = self._since(now)
        with self.lock:
            rows = list(self._by_pat.get(patient_id, ()))
        return [r for r in rows if (since is None or r["at"] >= since) and r["conv_id"] != exclude_conv]

    def prior(self, patient_id: str, ref: str, *, exclude_conv: str | None = None) -> list[dict[str, Any]]:
        """다른 대화에서 이 과거 환자에 대해 나간 값 (kcalc 입력 모양, 대화마다 사건 묶음을 따로). 같은 값은 한 번만."""
        out, seen = [], set()
        for r in self.entries(patient_id, exclude_conv=exclude_conv):
            g = f"{ref}:{r['conv_id']}:{r['event_label']}" if r["event_label"] else None
            key = (r["attribute"], r["node_id"], g)
            if key in seen:
                continue
            seen.add(key)
            out.append(dict(attribute=r["attribute"], node_id=r["node_id"], event_group=g))
        return out

    def summary(self, patient_id: str, *, exclude_conv: str | None = None) -> dict[str, Any]:
        """관제 화면용: 다른 대화에서 나간 값의 수 · 대화 수 · 계정 수 · 마지막 시각 (값 자체는 넣지 않는다)."""
        rows = self.entries(patient_id, exclude_conv=exclude_conv)
        return dict(values=len({(r["attribute"], r["node_id"]) for r in rows}), conversations=len({r["conv_id"] for r in rows}),
                    users=len({r["user_id"] for r in rows if r["user_id"] is not None}),
                    approvals=sum(1 for r in rows if r["kind"] == "approval"),
                    last_at=max((r["at"] for r in rows), default=None))

    def describe(self) -> dict[str, Any]:
        with self.lock:
            n = sum(len(v) for v in self._by_pat.values())
            pats = len(self._by_pat)
        return dict(on=True, windowDays=self.window_days if self.window else None, entries=n, patients=pats,
                    persistent=self.store is not None)
