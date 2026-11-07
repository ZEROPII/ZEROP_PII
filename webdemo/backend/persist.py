# 의료진 대화를 DB에 남긴다 (python -m medicloak). 서버를 다시 켜도 관제 화면 · 의료진 대화 분석에서 읽을 수 있게 한다.
#
#   conversation.row_json      관제 목록 한 줄 (monitor.row)
#   conversation.security_json 세 조건의 원 응답 · 판정 · k (monitor.detail이 열람 전에는 mask해서 보낸다)
#   conversation.clinic_json   의료진 화면 계약 전체 스냅숏 (clinic.ClinicConversation.snapshot, 숫자 포함 · 원래 값 없음)
#   turn_record                조건마다 턴 기록 (medical/session.py ArmRun._turn 기록 그대로, 원 응답 포함)
# 저장은 의료진 질문 · 새 대화 · 메시지 · 검토 표시가 있을 때마다 한다. 시뮬레이션 대화는 남기지 않는다 (켤 때마다 다시 만든다).
# 남기지 않는 것: 진행 중인 연구 모듈 상태(ArmRun). 그래서 서버를 다시 켜면 지난 대화는 읽기 전용이 된다.

from __future__ import annotations

import json
from typing import Any

from webdemo.backend.clinic import ArchivedConversation, ClinicConversation, DeskRegistry
from webdemo.backend.engine import ARMS, Engine
from webdemo.backend.monitor import Monitor
from webdemo.backend.store import Store


class Persist:
    def __init__(self, store: Store, eng: Engine) -> None:
        self.store, self.eng = store, eng
        self.monitor: Monitor | None = None
        self.registry: DeskRegistry | None = None
        self.errors = 0

    def save(self, conv: ClinicConversation, why: str = "") -> None:
        """
        스냅숏은 엔진 잠금 안에서 만들고, DB 쓰기까지를 대화별 잠금(save_lock)으로 묶는다: 질문 스레드 · 비교 갈래 스레드 ·
        관제 쪽 저장이 겹쳐도 앞 턴의 스냅숏이 뒤 턴 것을 덮어쓰지 않는다. 잠금 순서는 save_lock → 엔진 → DB.
        """
        s = conv.session
        if s.source != "clinic":
            return
        with conv.save_lock:
            self._save(conv, s)

    def _save(self, conv: ClinicConversation, s: Any) -> None:
        try:
            with self.eng.lock:
                row = self.monitor.row(s) if self.monitor else None
                sec = s.security_view()
                snap = conv.snapshot()
                new = [(a, r["turn"], r) for a in ARMS for r in s.logs[a]
                       if r.get("turn") is not None and (a, r["turn"]) not in conv.saved_turns]
                owner = s.owner or {}
                cols = dict(user_id=owner.get("user_id"), owner_label=owner.get("label"), source=s.source, trial_id=s.trial_id,
                            patient_fhir_id=(s.launch or {}).get("fhirId") or s.patient_id, llm_mode=s.llm_mode, started_at=s.created,
                            last_active=s.last_active, turns=s.turn, review_json=s.review, row_json=row, security_json=sec, clinic_json=snap)
            self.store.save_conversation(s.id, **cols)
            for a, t, r in new:
                self.store.add_turn(s.id, a, t, r)
                conv.saved_turns.add((a, t))
        except Exception:
            self.errors += 1
            raise

    def save_session(self, s: Any) -> None:
        """관제 쪽 변화(메시지 · 검토 표시) 뒤: 그 대화가 의료진 대화면 다시 저장한다."""
        if self.registry is None or getattr(s, "source", None) != "clinic":
            return
        conv = self.registry.live(s.id)
        if conv is not None:
            self.save(conv, "monitor")

    def evict(self, conv: ClinicConversation) -> None:
        """
        메모리에서 내린 지난 대화: 마지막으로 저장하고, 저장이 끝난 뒤에만 엔진 세션 목록에서 뺀다 (관제 화면에는 DB 스냅숏으로
        남는다). 저장이 실패하면 예외를 올려 ClinicDesk가 대화를 메모리에 그대로 두게 한다.
        """
        self.save(conv, "evict")
        with self.eng.lock:
            self.eng.sessions.pop(conv.id, None)

    def archive(self, sid: str) -> ArchivedConversation | None:
        c = self.store.conversation(sid)
        if c is None or not c.get("clinic"):
            return None
        return ArchivedConversation(c, self.store.messages_of(sid))

    def next_id(self) -> int:
        """
        세션 · 작업 번호를 DB에 남은 가장 큰 번호 다음부터 잇는다 (S0007 다음은 S0008).
        저장한 대화뿐 아니라 감사 기록이 가리킨 대화 · 레드팀 작업 번호도 본다: 저장하지 않는 시뮬레이션 대화(S…)나
        작업(R…)의 번호를 다시 쓰면, 지난 감사 기록이 엉뚱한 대화를 가리키게 되기 때문이다.
        """
        ids = [r["conv_id"] for r in self.store.q("SELECT conv_id FROM conversation")]
        ids += [r["job_id"] for r in self.store.q("SELECT job_id FROM redteam_run")]
        for r in self.store.q("SELECT conv_id, detail_json FROM audit"):
            ids.append(r["conv_id"] or "")
            try:
                ids.append(str(json.loads(r["detail_json"] or "{}").get("job") or ""))
            except ValueError:
                pass
        best = max((int(x[1:]) for x in ids if len(x) > 1 and x[0] in "SR" and x[1:].isdigit()), default=0)
        return best + 1
