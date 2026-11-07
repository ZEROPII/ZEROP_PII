# EMR 접근 관리 (ADR-0034 · ADR-0036): 담당 배정 규칙 · 예외 열람 · 등록번호 · 협진 의뢰 · 접근 기록 · 차트 요약 · assign 명령.
# DB만 쓴다 (엔진 · 앱 없음).
import json
import re
import time

import pytest

from medicloak.cli import main
from webdemo.backend import emr
from webdemo.backend.access import EmrAccess, subject_tag, tag_key
from webdemo.backend.auth import add_user, ensure_initial_accounts
from webdemo.backend.fhir import OutpatientEmr
from webdemo.backend.store import Store

PW = "pw-test-1234"


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    """가상 EMR과 처음 계정 셋(의료진 둘 · 보안 담당자 하나)을 넣은 DB 파일. 테스트마다 배정 · 열람은 지우고 시작한다."""
    path = tmp_path_factory.mktemp("assign") / "mc.db"
    s = Store(path)
    emr.load_csv(s, log=lambda _: None)
    ensure_initial_accounts(s, PW, None)
    s.close()
    return path


@pytest.fixture
def store(db):
    s = Store(db)
    for t in ("emr_assignment", "emr_grant", "emr_access", "emr_consult", "audit"):
        s.x(f"DELETE FROM {t}")
    s.x("DELETE FROM app_user WHERE username NOT IN ('doctor1', 'doctor2', 'privacy1')")
    yield s
    s.close()


def uid(store, name: str) -> int:
    return store.user_by_name(name)["user_id"]


def test_fill_splits_by_patient_number_and_keeps_existing(store):
    acc = EmrAccess(store)
    pats = acc.outpatients()
    assert len(pats) == 115 and pats == sorted(pats)
    got = acc.fill()
    assert got == dict(assigned=115, counts=dict(doctor1=58, doctor2=57))
    # 번호 순서대로 번갈아 (담당이 가장 적은 계정, 같으면 먼저 만든 계정): 보안 담당자 계정은 받지 않는다
    team = acc.team()
    assert [team[f][0]["username"] for f in pats[:4]] == ["doctor1", "doctor2", "doctor1", "doctor2"]
    assert not acc.assigned_ids(uid(store, "privacy1"))
    assert acc.fill()["assigned"] == 0                                    # 다시 켜도 그대로
    # 의료진을 더해도 담당이 있는 환자는 옮기지 않는다. --reset이면 셋이 다시 나눈다
    add_user(store, "doctor3", "최하린", "clinician", "소아청소년과", PW)
    assert acc.fill()["assigned"] == 0 and not acc.assigned_ids(uid(store, "doctor3"))
    got = acc.fill(reset=True)
    assert got["assigned"] == 115 and sorted(got["counts"].values()) == [38, 38, 39]
    assert sum(len(v) for v in acc.team().values()) == 115
    d = acc.describe()
    assert d["unassigned"] == 0 and d["outpatients"] == 115 and [c["assigned"] for c in d["clinicians"]] == [39, 38, 38]


def test_fill_needs_a_clinician_account(tmp_path):
    s = Store(tmp_path / "empty.db")
    emr.load_csv(s, log=lambda _: None)
    assert EmrAccess(s).fill() == dict(assigned=0, counts={})
    s.close()


def test_resolve_patient_number(store):
    acc = EmrAccess(store)
    f = acc.outpatients()[3]
    assert acc.resolve(f[:8]) == f and acc.resolve(f[:8].upper()) == f and acc.resolve(f" {f} ") == f
    assert acc.resolve(f[:7]) is None and acc.resolve("zzzzzzzz") is None and acc.resolve("") is None
    past = store.one("SELECT fhir_id FROM emr_patient WHERE cohort != 'QUERY_POOL'")["fhir_id"]
    assert acc.resolve(past[:8]) is None                                   # 과거 기록 환자는 외래 환자가 아니다


def test_break_glass_grant_rules(store):
    acc = EmrAccess(store, hours=12)
    acc.fill()
    u1 = uid(store, "doctor1")
    other = next(f for f in acc.outpatients() if f not in acc.assigned_ids(u1))
    assert acc.via(u1, other) is None
    with pytest.raises(ValueError):
        acc.open_grant(u1, other, "consult", "짧음")
    with pytest.raises(ValueError):
        acc.open_grant(u1, other, "curious", "궁금해서 열어 봅니다")
    g, created = acc.open_grant(u1, other, "consult", "호흡기내과 협진 의뢰")
    assert created and g["active"] and g["reasonLabel"] == "협진" and abs(g["expiresAt"] - g["createdAt"] - 12 * 3600) < 1
    assert acc.open_grant(u1, other, "on_call", "또 눌러도 하나")[1] is False
    assert acc.via(u1, other) == ("break_glass", acc.active_grants(u1)[other])
    assert acc.visible(u1)[other][0] == "break_glass" and acc.pending() == 1
    # 검토: 적절함은 열람을 그대로 두고, 확인 필요는 바로 끝낸다
    ok = acc.review(g["id"], "ok", None, by="이하늘")
    assert ok["review"] == "ok" and ok["active"] and acc.pending() == 0
    flag = acc.review(g["id"], "flag", "협진 기록 없음", by="이하늘")
    assert flag["review"] == "flag" and not flag["active"] and flag["endedAt"] and acc.via(u1, other) is None
    with pytest.raises(ValueError):
        acc.review(g["id"], "nope", None, by="이하늘")
    with pytest.raises(KeyError):
        acc.review(999999, "ok", None, by="이하늘")
    # 기한이 지나면 열리지 않는다
    short = EmrAccess(store, hours=0.5 / 3600)
    g2, _ = short.open_grant(u1, other, "other", "잠깐만 엽니다")
    time.sleep(0.6)
    assert short.via(u1, other) is None and not short.grant(g2["id"])["active"]
    # 예외 열람을 끄면 새로 열 수 없고, 열어 둔 것도 쓰지 않는다
    acc.open_grant(u1, other, "consult", "다시 협진 의뢰")
    off = EmrAccess(store, break_glass=False)
    with pytest.raises(PermissionError):
        off.open_grant(u1, other, "consult", "꺼진 서버에서 열기")
    assert off.via(u1, other) is None and other not in off.visible(u1) and acc.via(u1, other)[0] == "break_glass"


def test_access_log_dedup_and_stats(store):
    acc = EmrAccess(store)
    f = acc.outpatients()[0]
    u1 = uid(store, "doctor1")
    assert acc.record(u1, f, "fhir", via="assigned", dedup=600)
    assert not acc.record(u1, f, "fhir", via="assigned", dedup=600)        # 같은 일은 한 번으로
    assert acc.record(u1, f, "denied", detail="chart", dedup=60) and acc.record(u1, f, "denied", detail="launch", dedup=60)
    assert not acc.record(u1, f, "denied", detail="chart", dedup=60)
    assert acc.record(u1, f, "chart", via="assigned")
    h = acc.history(f)
    assert [x["action"] for x in h] == ["chart", "denied", "denied", "fhir"] and h[0]["displayName"] == "김서연"
    st = acc.stats(time.time() - 60)[f]
    assert st["recent"] == 4 and st["denied"] == 2 and st["last"]["action"] == "chart"
    assert acc.count_since(time.time() - 60, ("chart", "fhir")) == 2


def test_monitor_tag_and_cli_tag_are_the_same(store):
    from webdemo.backend.monitor import Monitor
    f = EmrAccess(store).outpatients()[5]
    tag = Monitor(None, store).tag(f)  # type: ignore[arg-type]
    assert tag == subject_tag(tag_key(store), f) == subject_tag(tag_key(store), f[:8]) and tag.startswith("P-") and len(tag) == 8


def test_chart_summary(store):
    e = OutpatientEmr(store)
    acc = EmrAccess(store)
    f = max(acc.outpatients(), key=lambda x: store.one("SELECT n_events FROM emr_patient WHERE fhir_id = ?", (x,))["n_events"])
    c = e.chart(f)
    assert {"birthYear", "birthDate", "region", "address"}.isdisjoint(c["patient"]) and c["patient"]["identifier"] == f[:8]
    for k in ("problems", "medications", "procedures", "carePlans"):
        items = c[k]["items"]
        assert len(items) <= 10 and c[k]["total"] >= len(items)
        flags = [x["active"] for x in items]
        assert flags == sorted(flags, reverse=True)                        # 끝나지 않은 것 먼저
        for active in (True, False):
            lasts = [x["last"] or "" for x in items if x["active"] == active]
            assert lasts == sorted(lasts, reverse=True)                    # 그 안에서는 최근 것부터
        assert all(x["ended"] is None for x in items if x["active"])
    assert c["problems"]["total"] == len({r["code_node"] for r in store.q(
        "SELECT code_node FROM emr_event WHERE patient_id = ? AND event_type = 'CONDITION'", (f,))})
    assert len(c["visits"]) <= 8 and [v["date"] for v in c["visits"]] == sorted((v["date"] for v in c["visits"]), reverse=True)
    assert 1 <= len(c["yearly"]) <= 10 and c["yearly"][-1]["year"] == int(c["visits"][0]["date"][:4])
    assert c["visitDays"] >= len(c["visits"]) and c["firstRecord"] <= c["visits"][-1]["date"]
    # 진료 지원 AI 목적이 없는 외래 환자도 연령대를 낼 수 있다
    assert all(e.age_band(x) for x in acc.outpatients()[:10])


def test_assign_cli_changes_are_audited_without_patient_numbers(db, store, capsys):
    acc = EmrAccess(store)
    main(["--db", str(db), "assign", "auto"])
    out = capsys.readouterr().out
    assert "115명" in out and "doctor1 58명" in out
    main(["--db", str(db), "assign"])
    out = capsys.readouterr().out
    assert "담당  58명" in out and "담당 없음 0명" in out
    f = next(x for x in acc.outpatients() if x not in acc.assigned_ids(uid(store, "doctor2")))
    main(["--db", str(db), "assign", "add", f[:8], "doctor2"])
    assert "더했습니다" in capsys.readouterr().out and acc.via(uid(store, "doctor2"), f) == ("assigned", None)
    main(["--db", str(db), "assign", "add", f[:8], "doctor2"])
    assert "바뀐 것이 없습니다" in capsys.readouterr().out
    main(["--db", str(db), "assign", "list", "--patient", f[:8]])
    assert "김서연(doctor1)" in capsys.readouterr().out
    main(["--db", str(db), "assign", "remove", f[:8], "doctor2"])
    assert "뺐습니다" in capsys.readouterr().out and acc.via(uid(store, "doctor2"), f) is None
    with pytest.raises(SystemExit):
        main(["--db", str(db), "assign", "add", f[:8], "privacy1"])         # 보안 담당자는 담당이 될 수 없다
    with pytest.raises(SystemExit):
        main(["--db", str(db), "assign", "add", "00000000", "doctor2"])
    main(["--db", str(db), "assign", "auto", "--reset"])
    assert "다시 나눴습니다" in capsys.readouterr().out
    audit = store.audit_entries()
    assigns = [a for a in audit if a["action"] == "emr_assign"]
    assert len(assigns) == 4 and [a.get("change") for a in assigns] == [None, "add", "remove", None]
    assert assigns[1]["patient_tag"] == subject_tag(tag_key(store), f) and f[:8] not in json.dumps(audit)
    assert all(a["actor"].startswith("운영자 명령") for a in assigns)


def test_registration_numbers_are_stable_random_and_resolve(store):
    """등록번호 (ADR-0036): 외래 환자마다 하나, 겹치지 않고, 다시 켜도 그대로. 차례대로가 아니다. 등록번호 · 환자 번호로 찾는다."""
    acc = EmrAccess(store)
    acc.fill()
    nos = acc.regnos()
    pats = acc.outpatients()
    assert set(nos) == set(pats) and len(set(nos.values())) == len(pats)
    assert all(re.fullmatch(r"26-\d{4}", n) for n in nos.values())
    assert acc.number() == 0 and acc.regnos() == nos                       # 다시 켜도 그대로
    ordered = [int(nos[f][3:]) for f in pats]
    assert ordered != sorted(ordered)                                       # 환자 순서대로 늘어나는 번호가 아니다
    f = pats[3]
    assert acc.resolve(nos[f]) == f and acc.resolve(nos[f].replace("-", "")) == f and acc.resolve(f" {nos[f]} ") == f
    assert acc.resolve(f[:8]) == f                                          # 환자 번호 앞 8자리도 받는다
    free = next(f"26-{n:04d}" for n in range(1000, 10000) if f"26-{n:04d}" not in nos.values())
    assert acc.resolve(free) is None and acc.resolve("26-12") is None


def test_consult_request_opens_without_a_number_and_ends_on_cancel(store):
    """협진 의뢰 (ADR-0036): 담당 의료진이 보내고, 받은 의료진이 번호 없이 연다. 거절 · 취소 · 기한. --break-glass off여도 쓴다."""
    acc = EmrAccess(store, hours=12)
    acc.fill()
    u1, u2 = uid(store, "doctor1"), uid(store, "doctor2")
    f = sorted(acc.assigned_ids(u1))[0]
    assert acc.via(u2, f) is None
    assert [d["username"] for d in acc.directory(except_user=u1)] == ["doctor2"]
    with pytest.raises(ValueError):
        acc.send_consult(u1, f, u2, "짧음")
    with pytest.raises(ValueError):
        acc.send_consult(u1, f, u1, "자기 자신에게 보내기")
    c, created = acc.send_consult(u1, f, u2, "당뇨 신장 합병증 협진 부탁드립니다")
    assert created and c["status"] == "pending" and c["open"] and c["sender"]["username"] == "doctor1" and c["receiver"]["username"] == "doctor2"
    assert acc.send_consult(u1, f, u2, "한 번 더 눌러도 하나입니다")[1] is False and acc.open_consults(u2) == 1
    got = acc.consults(u2)
    assert [x["id"] for x in got["received"]] == [c["id"]] and acc.consults(u1)["sent"][0]["id"] == c["id"]
    with pytest.raises(KeyError):
        acc.open_consult(c["id"], u1)                                        # 보낸 사람은 의뢰로 열지 않는다
    c2, g, made = acc.open_consult(c["id"], u2)
    assert made and c2["status"] == "opened" and g["consultId"] == c["id"] and g["reason"] == "consult" and "협진 의뢰" in g["note"]
    assert acc.via(u2, f) == ("consult", acc.active_grants(u2)[f]) and acc.visible(u2)[f][0] == "consult"
    assert acc.open_consult(c["id"], u2)[2] is False                         # 다시 열면 같은 열람
    assert acc.grants()[0]["consult"]["fromName"] == store.user_by_name("doctor1")["display_name"] and acc.pending() == 1
    # --break-glass off: 스스로 여는 예외 열람은 쓰지 않지만 협진 의뢰로 연 것은 쓴다
    off = EmrAccess(store, break_glass=False)
    assert off.via(u2, f)[0] == "consult"
    # 받은 사람이 이미 담당이면 보내지 않는다
    acc.assign(f, u2, "test")
    with pytest.raises(ValueError):
        acc.send_consult(u1, f, u2, "이미 담당인데 보내기")
    acc.unassign(f, u2)
    # 보낸 사람이 취소하면 그 의뢰로 연 열람도 끝난다
    with pytest.raises(KeyError):
        acc.close_consult(c["id"], u2, "canceled")                           # 받은 사람은 취소하지 못한다 (거절은 한다)
    done = acc.close_consult(c["id"], u1, "canceled", "환자가 전원했습니다")
    assert done["status"] == "canceled" and not done["open"] and acc.via(u2, f) is None
    with pytest.raises(PermissionError):
        acc.open_consult(c["id"], u2)
    # 거절 · 기한
    c3, _ = acc.send_consult(u1, f, u2, "다시 협진 부탁드립니다")
    assert acc.close_consult(c3["id"], u2, "declined")["statusLabel"] == "거절함" and acc.open_consults(u2) == 0
    c4, _ = acc.send_consult(u1, f, u2, "세 번째 협진 의뢰입니다")
    store.x("UPDATE emr_consult SET expires_at = ? WHERE consult_id = ?", (time.time() - 1, c4["id"]))
    assert acc.consult(c4["id"])["status"] == "expired" and acc.open_consults(u2) == 0
    with pytest.raises(PermissionError):
        acc.open_consult(c4["id"], u2)


def test_old_database_gets_new_columns(tmp_path):
    """예전 DB(협진 의뢰 칸이 없는 emr_grant)를 열면 칸을 붙인다."""
    import sqlite3
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE emr_grant (grant_id INTEGER PRIMARY KEY AUTOINCREMENT, fhir_id TEXT NOT NULL, user_id INTEGER NOT NULL, "
                "reason TEXT NOT NULL, note TEXT, created_at REAL NOT NULL, expires_at REAL NOT NULL, ended_at REAL, review TEXT, "
                "review_note TEXT, reviewed_at REAL, reviewed_by TEXT)")
    con.commit()
    con.close()
    s = Store(path)
    assert "consult_id" in {r[1] for r in s.conn.execute("PRAGMA table_info(emr_grant)")}
    s.close()
