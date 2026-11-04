# 의료진 대화의 대상 AI(LLM) 만들기와 동시 호출 처리
#
#   real    : .env의 LLM_API_KEY · LLM_API_BASE · LLM_MODEL (core.config) → medical.llm.ClientRoleLLM
#   dry-run : medical.llm.MockRoleLLM (배선 확인용. 키 없이 흐름만 확인하며 답 내용에는 의미가 없다)
#   oracle  : LLM 없음. 질문 뜻을 찾아 Seed를 고르는 결정적 응답기 (python -m webdemo와 같음)
#
# 키 값은 어디에도 출력하지 않는다. 설정 확인은 변수 이름과 설정 여부만 보여 준다 (core.config.Settings.describe).

from __future__ import annotations

import threading
import time
from typing import Any

LLM_CHOICES = ("real", "dry-run", "oracle")
ORACLE_LABEL = "결정적 응답기 (LLM 호출 없음)"
DRY_RUN_LABEL = "배선 확인용 가짜 LLM (dry-run, 답 내용 의미 없음)"


_BACKGROUND = threading.local()


def background_calls() -> None:
    """이 스레드의 LLM 호출을 '뒤로 미룸'으로 표시한다 (비교 갈래 계산 스레드). 의료진 질문이 기다리면 먼저 보낸다."""
    _BACKGROUND.low = True


class _Slots:
    """동시 호출 수 n. 의료진 질문(앞) 호출이 기다리고 있으면 비교 갈래(뒤) 호출은 자리가 나도 양보한다."""

    def __init__(self, n: int) -> None:
        self.n = max(1, int(n))
        self.busy = 0
        self.waiting_front = 0
        self.waiting_back = 0
        self.cv = threading.Condition()

    def acquire(self, back: bool) -> None:
        with self.cv:
            if back:
                self.waiting_back += 1
            else:
                self.waiting_front += 1
            try:
                while self.busy >= self.n or (back and self.waiting_front > 0):
                    self.cv.wait()
                self.busy += 1
            finally:
                if back:
                    self.waiting_back -= 1
                else:
                    self.waiting_front -= 1

    def release(self) -> None:
        with self.cv:
            self.busy -= 1
            self.cv.notify_all()


class LiveLLM:
    """
    의료진 대화용 LLM을 감싼다.
      - 네트워크 호출 동안 엔진 잠금(RLock)을 모두 풀었다가 호출이 끝나면 같은 횟수만큼 다시 잡는다.
        한 의료진의 질문이 LLM 답을 기다리는 동안에도 다른 의료진 화면과 관제 화면 요청이 돈다.
        연구 모듈(ArmRun._turn)은 대상 AI · 추출기 · 재작성기 호출을 모두 마친 뒤에만 State를 바꾸므로,
        잠금이 풀린 사이에 다른 요청이 보는 State는 늘 앞 턴까지의 것이다. 같은 대화의 질문은 ClinicDesk 잠금이 줄 세운다.
      - 동시 호출 수를 제한한다. 기본 1이면 .env LLM_MIN_INTERVAL_SEC 간격 제한(core.llm_client)이 그대로 지켜진다.
      - 비교 갈래(C1S) 계산 스레드의 호출은 의료진 질문 호출에 자리를 양보한다 (background_calls).
    """

    def __init__(self, inner: Any, lock: Any, *, concurrency: int = 1) -> None:
        self.inner = inner
        self.lock = lock
        self.concurrency = max(1, int(concurrency))
        self._slots = _Slots(self.concurrency)

    @property
    def usage(self) -> list[dict[str, Any]]:
        return self.inner.usage

    @property
    def waiting(self) -> int:
        """자리를 기다리는 의료진 질문 호출 수 (/api/health 표시용)."""
        return self._slots.waiting_front

    def complete(self, role: str, system: str, messages: list[dict[str, str]], **kw: Any) -> str:
        held = 0
        while True:                      # 이 스레드가 잡은 만큼 모두 푼다 (잡지 않았으면 RuntimeError로 바로 끝)
            try:
                self.lock.release()
            except RuntimeError:
                break
            held += 1
        try:
            self._slots.acquire(back=bool(getattr(_BACKGROUND, "low", False)))
            try:
                return self.inner.complete(role, system, messages, **kw)
            finally:
                self._slots.release()
        finally:
            for _ in range(held):
                self.lock.acquire()


def make_live_llm(choice: str, cfg: Any, env_file: str | None = None) -> tuple[Any | None, str]:
    """(LLM 또는 None, 화면 표시 이름). real은 .env를 읽는다 (없거나 비었으면 core.config.ConfigError, 메시지에 값 없음)."""
    if choice == "oracle":
        return None, ORACLE_LABEL
    if choice == "dry-run":
        from medical.llm import MockRoleLLM
        return MockRoleLLM(), DRY_RUN_LABEL
    if choice != "real":
        raise ValueError(f"--llm은 {', '.join(LLM_CHOICES)} 중 하나입니다: {choice}")
    from core.config import get_settings
    from core.llm_client import LLMClient
    from medical.llm import ClientRoleLLM
    s = get_settings(env_file)
    return ClientRoleLLM(LLMClient(s), models=dict(cfg.models), temperature=cfg.temperature), f"실제 LLM ({s.llm_model})"


def check_llm(env_file: str | None = None, *, send: bool = True, out=print) -> bool:
    """
    .env를 읽어 설정을 보여 주고(키 값 없이), send면 짧은 요청을 한 번 보낸다. 성공하면 True.
    python -m medicloak check-llm 이 쓴다.
    """
    from core.config import ConfigError, get_settings
    from core.llm_client import LLMClient, LLMError
    try:
        s = get_settings(env_file)
    except ConfigError as exc:
        out(f"[설정 오류] {exc}")
        return False
    d = s.describe()
    out("설정을 읽었습니다 (키 값은 보여 주지 않습니다)")
    for k in ("llm_api_base", "llm_model", "llm_max_tokens", "llm_timeout_sec", "llm_max_retries", "llm_min_interval_sec", "llm_api_key_set"):
        out(f"  {k} = {d[k]}")
    if not send:
        return True
    t0 = time.time()
    try:
        with LLMClient(s) as c:
            r = c.complete("다음 낱말을 그대로 한 번만 쓰세요: 확인", max_tokens=16, temperature=0)
    except LLMError as exc:
        out(f"[호출 실패] {type(exc).__name__}: {exc}")
        return False
    out(f"호출 성공 {time.time() - t0:.1f}초 · 모델 {r.model} · 입력 {r.input_tokens} · 출력 {r.output_tokens} 토큰 · 답 '{r.text.strip()[:20]}'")
    return True
