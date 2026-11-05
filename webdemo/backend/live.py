# 의료진 대화의 대상 AI(LLM) 만들기와 동시 호출 처리
#
#   real    : .env의 LLM_API_KEY · LLM_API_BASE · LLM_MODEL (core.config) → medical.llm.ClientRoleLLM
#   dry-run : medical.llm.MockRoleLLM (배선 확인용. 키 없이 흐름만 확인하며 답 내용에는 의미가 없다)
#   oracle  : LLM 없음. 질문 뜻을 찾아 Seed를 고르는 결정적 응답기 (python -m webdemo와 같음)
#
# 키 값은 어디에도 출력하지 않는다. 설정 확인은 변수 이름과 설정 여부만 보여 준다 (core.config.Settings.describe).

from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any

LLM_CHOICES = ("real", "dry-run", "oracle")
ORACLE_LABEL = "결정적 응답기 (LLM 호출 없음)"
DRY_RUN_LABEL = "연결 점검 모드 (dry-run · 실제 LLM을 부르지 않음)"


# 질문 문장을 만드는 역할. 의료진 대화의 사례 검색 질문(턴 0)은 시스템이 보내는 질문이라 결정적 응답기가 만든다.
QUESTION_ROLES = frozenset({"mutator", "checker", "doc_writer"})

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

    def sibling(self, inner: Any) -> "LiveLLM":
        """같은 자리(동시 호출 수 · 의료진 질문 우선)를 나눠 쓰는 다른 LLM (레드팀 실행이 호출 수를 따로 세려고 씀)."""
        s = LiveLLM.__new__(LiveLLM)
        s.inner, s.lock, s.concurrency, s._slots = inner, self.lock, self.concurrency, self._slots
        return s

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


def make_live_llm(choice: str, cfg: Any, env_file: str | None = None, *, role_models: dict[str, str] | None = None) -> tuple[Any | None, str]:
    """
    (LLM 또는 None, 화면 표시 이름). real은 .env를 읽는다 (없거나 비었으면 core.config.ConfigError, 메시지에 값 없음).
    role_models: 역할별 모델 (예: 추출기 · 재작성기만 빠른 모델). 없는 역할은 .env의 LLM_MODEL.
    """
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
    models = dict(cfg.models, **{r: m for r, m in (role_models or {}).items() if m})
    extra = "".join(f" · {ROLE_KO.get(r, r)} {m}" for r, m in sorted(models.items()) if m != s.llm_model)
    return ClientRoleLLM(LLMClient(s), models=models, temperature=cfg.temperature), f"실제 LLM ({s.llm_model}{extra})"


# 실제 LLM 대상 AI에게 붙이는 답 형식 (진료 화면에서 읽기 쉽고, 생성 · 추출 · 재작성 호출이 짧아진다).
# 의료진 대화와 실제 LLM 레드팀에 똑같이 붙인다: 방어 효과를 잰 조건과 운영 조건이 같아야 레드팀 수치로 운영을 설명할 수 있다.
# serve --answer-style off로 둘 다 끈다 (비교 실험용). 레드팀 실행 기록에 켬 · 끔과 지시문 해시를 남긴다.
ANSWER_STYLE = """[답 형식]
이 답은 진료 중인 의사의 화면에 그대로 보입니다.
- 사례마다 짧은 문장 두세 개로 씁니다. 표, 머리글(#), 굵은 글씨(**)는 쓰지 않습니다.
- 질문에 답하는 데 필요한 값만 씁니다. 묻지 않은 날짜 · 나이 · 지역 · 횟수는 덧붙이지 않습니다.
- 기록에 없는 내용은 '-'로 채우지 말고 쓰지 않습니다."""


ANSWER_STYLE_ID = "short-v1:" + hashlib.sha256(ANSWER_STYLE.encode("utf-8")).hexdigest()[:8]


def styled(role: str, system: str) -> str:
    """대상 AI(target) 지시문 끝에 답 형식을 붙인다. 다른 역할 · 이미 붙은 지시문은 그대로."""
    return f"{system}\n\n{ANSWER_STYLE}" if role == "target" and ANSWER_STYLE not in system else system


ROLE_KO = {"extractor": "추출기", "rewriter": "재작성기", "target": "대상 AI", "mutator": "공격 질문", "checker": "질문 확인", "reviewer": "검토 보조"}


class AnswerStyleLLM:
    """실제 LLM을 감싼다. 대상 AI 지시문 끝에 답 형식을 붙이고, 다른 역할은 그대로 보낸다."""

    style_id = ANSWER_STYLE_ID                          # 첫 답 나눠 쓰기의 키에 넣는다 (답 형식이 다르면 다른 요청)

    def __init__(self, inner: Any) -> None:
        self.inner = inner

    def __getattr__(self, name: str) -> Any:          # usage · waiting …
        return getattr(self.inner, name)

    def complete(self, role: str, system: str, messages: list[dict[str, str]], **kw: Any) -> str:
        return self.inner.complete(role, styled(role, system), messages, **kw)


class Turn0Cache:
    """
    첫 답(턴 0) 요청과 받은 답을 대화 사이에 나눠 쓴다. 같은 환자 · 같은 진료 목적이면 검색 사례 · 질문 · 지시문이 같아 요청이
    글자까지 같다(온도 0). 다른 의료진이 같은 환자를 열거나 다시 열 때 실제 LLM을 다시 부르지 않는다. 메모리에만 둔다.
    키는 요청의 SHA-256이다 (request_key). 지시문에는 검색된 과거 환자 기록이 들어 있어 원문을 키로 두지 않는다.
    """

    def __init__(self, cap: int = 4000) -> None:
        self.cap = cap
        self.lock = threading.Lock()
        self.answers: dict[str, list[str]] = {}

    def get(self, key: str, n: int) -> str | None:
        with self.lock:
            got = self.answers.get(key)
            return got[n] if got is not None and n < len(got) else None

    def put(self, key: str, n: int, out: str) -> None:
        with self.lock:
            got = self.answers.setdefault(key, [])
            if len(got) == n:
                got.append(out)
            while len(self.answers) > self.cap:                 # 오래된 요청부터 지운다
                self.answers.pop(next(iter(self.answers)))

    def forget(self, keys: set[str]) -> None:
        with self.lock:
            for k in keys:
                self.answers.pop(k, None)


class CallWatchLLM:
    """
    의료진 대화(화면 갈래 C1)의 실제 LLM을 감싼다. watch(role, n)가 걸려 있는 동안 실제로 부르기 직전에 알린다
    (질문을 보내고 기다리는 동안의 진행 표시). 비교 갈래는 감싸지 않아 뒤에서 도는 호출이 섞이지 않는다.
    """

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.watch: Any = None
        self.calls = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def complete(self, role: str, system: str, messages: list[dict[str, str]], **kw: Any) -> str:
        w = self.watch
        if w is not None:
            self.calls += 1
            try:
                w(role, self.calls)
            except Exception:                                    # 진행 표시가 실패해도 호출은 한다
                pass
        return self.inner.complete(role, system, messages, **kw)


def request_key(style: str, role: str, system: str, messages: list[dict[str, str]]) -> str:
    """첫 답 나눠 쓰기의 키: 답 형식 판 · 역할 · 지시문 · 대화를 이은 글의 SHA-256 (원문은 남기지 않는다)."""
    raw = "\x00".join((style, role, system, json.dumps(messages, ensure_ascii=False)))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class Turn0LLM:
    """
    의료진 대화의 첫 답(턴 0, 사례 검색)을 만들 때 쓰는 LLM.
      - 사례 검색 질문 문장(mutator · checker)은 결정적 응답기가 만든다 (시스템이 보내는 검색 질문).
      - 대상 AI 답 · 단서 추출 · 재작성 · 확인 추출은 실제 LLM이 한다.
      - 턴 0에서는 C1과 C1S가 모두 빈 State에서 시작해 공개 계획과 재작성 요청이 똑같다. 그래서 다음 갈래(next_arm 뒤)는
        앞 갈래가 받은 답을 같은 요청의 차례대로 다시 쓴다. 한 갈래 안에서 같은 요청을 다시 보내면(형식이 틀려 다시 추출,
        재작성 두 번째 시도) 실제로 다시 부른다.
      - cache(Turn0Cache)를 주면 다른 대화가 받은 같은 요청의 답도 같은 차례대로 다시 쓴다. 첫 답이 거절이면 forget()으로
        이 대화가 쓴 요청을 지워 다음에 열 때 새로 부르게 한다.
      - on_call(role, n)은 실제로 부르기 직전에 알린다 (진료 지원 AI를 여는 화면의 진행 표시).
    """

    def __init__(self, live: Any, det: Any, *, cache: Turn0Cache | None = None, on_call: Any = None) -> None:
        self.live, self.det = live, det
        self.cache = cache if cache is not None else Turn0Cache()
        self.on_call = on_call
        self.keys: set[str] = set()
        self.calls = 0
        self._used: dict[str, int] = {}
        self.style = getattr(live, "style_id", "")       # 답 형식이 붙는 LLM이면 그 지시문 판

    def next_arm(self) -> None:
        """다음 갈래의 턴 0을 시작한다: 같은 요청을 처음부터 차례대로 다시 쓴다."""
        self._used = {}

    def forget(self) -> None:
        self.cache.forget(self.keys)

    def complete(self, role: str, system: str, messages: list[dict[str, str]], **kw: Any) -> str:
        if role in QUESTION_ROLES:
            return self.det.complete(role, system, messages, **kw)
        key = request_key(self.style, role, system, messages)
        n = self._used.get(key, 0)
        self._used[key] = n + 1
        self.keys.add(key)
        hit = self.cache.get(key, n)
        if hit is not None:
            return hit
        self.calls += 1
        if self.on_call is not None:
            try:
                self.on_call(role, self.calls)
            except Exception:                                    # 진행 표시가 실패해도 호출은 한다
                pass
        out = self.live.complete(role, system, messages, **kw)
        self.cache.put(key, n, out)
        return out


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
