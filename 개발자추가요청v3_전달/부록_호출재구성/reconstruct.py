"""기존 실행(연결 키 없음)의 llm_usage.jsonl 호출을 턴기록 순서로 재구성한다.
실행은 단일 스레드 순차 호출이므로, 코드 경로대로 기대 역할 순서를 만들고 실제 역할 순서와 한 줄씩 대조한다.
하나라도 어긋나면 중단하고 재구성 불가로 보고한다 (추정으로 채우지 않음)."""
import collections
import json
import sys
from pathlib import Path

R = Path(sys.argv[1])
U = [json.loads(l) for l in open(R / "llm_usage.jsonl", encoding="utf-8")]
T = [json.loads(l) for l in open(R / "턴기록.jsonl", encoding="utf-8")]
S = json.load(open(R / "trial요약.json", encoding="utf-8"))
arms = S["config"]["arms"]

pos = 0
out = []


def take(role, **tag):
    global pos
    u = U[pos]
    if u["role"] != role:
        raise SystemExit(f"MISMATCH at usage line {pos + 1}: expected {role}, got {u['role']} ({tag})")
    out.append(dict(tag, line=pos + 1, role=role, output_tokens=u["output_tokens"], truncated=u["truncated"]))
    pos += 1


def take_checks(checks, **tag):
    for c in checks or []:
        take("mutator", **tag)
        if not c.get("structural"):
            take("checker", **tag)


def take_extract_block(n, ok, **tag):
    for i in range(1, n + 1):
        parse_ok = (i == n and ok)
        take("extractor", attempt=i, parse_ok=parse_ok, **tag)


def take_release(rec, **tag):
    # 공개 확인 추출: 시도(attempt)마다 rewriter(LLM 재작성일 때만) → 추출 1~3회
    for j, at in enumerate(rec.get("release_attempts") or [], 1):
        if at["mode"] == "REWRITTEN":
            take("rewriter", release_attempt=j, **tag)
        failed = any(c.get("reason") == "EXTRACTION_FAILED" for c in at.get("checks") or [])
        # 성공 시 시도 수는 기록에 없음 → 연속된 extractor를 최대 3개까지 소비하되 첫 성공에서 멈춘다고 보고, 합계를 검증
        n = 0
        while pos < len(U) and U[pos]["role"] == "extractor" and n < 3:
            n += 1
            take("extractor", purpose="verify", release_attempt=j, attempt=n, **tag)
            if not failed:
                break  # 성공한 확인 추출은 첫 parse 성공에서 끝나지만, 앞선 실패 시도 수는 기록에 없음
    return


# 턴기록을 trial·갈래별로 순서대로 묶는다
by = collections.defaultdict(list)
for t in T:
    by[(t["trial_id"], t["arm"])].append(t)

tids = []
for t in S["trials"]:
    if t["trial_id"] not in tids:
        tids.append(t["trial_id"])

for tid in tids:
    t0 = next(r for r in by[(tid, arms[0])] if r.get("turn") == 0)
    take_checks(t0["checks"], trial_id=tid, arm="SHARED", turn=0, purpose="realize")
    take("target", trial_id=tid, arm="SHARED", turn=0, purpose="raw")
    take_extract_block(t0["extraction_tries"], t0["extraction_ok"], trial_id=tid, arm="SHARED", turn=0, purpose="raw")
    for arm in arms:
        for rec in by[(tid, arm)]:
            tag = dict(trial_id=tid, arm=arm, turn=rec.get("turn"))
            if rec.get("invalid_mutation"):
                take_checks(rec["checks"], purpose="realize", **tag)
                continue
            if rec["turn"] == 0:
                take_release(rec, **tag)
                continue
            take_checks(rec["checks"], purpose="realize", **tag)
            take("target", purpose="raw", **tag)
            take_extract_block(rec["extraction_tries"], rec["extraction_ok"], purpose="raw", **tag)
            take_release(rec, **tag)

print(f"aligned {pos}/{len(U)} usage lines")
if pos != len(U):
    raise SystemExit("leftover calls: reconstruction incomplete")
# release_extraction_tries 합계 검증
for (tid, arm), recs in by.items():
    for rec in recs:
        if rec.get("invalid_mutation"):
            continue
        n = sum(1 for o in out if o["trial_id"] == tid and o["arm"] == arm and o.get("turn") == rec["turn"] and o.get("purpose") == "verify")
        assert n == rec["release_extraction_tries"], (tid, arm, rec["turn"], n, rec["release_extraction_tries"])
print("release_extraction_tries totals match")
Path(sys.argv[2]).write_text("\n".join(json.dumps(o, ensure_ascii=False) for o in out) + "\n", encoding="utf-8")
