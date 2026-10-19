"""RAG 문서 사실표 검사 (시나리오 결정 D5, 2026-10-09).
사용: python check_rag_facts.py <사실표.csv> <노드_v0.9.csv> <사건연결표_v0.9.csv> [결과.json]
사실표 한 행 = 문서 안의 단서 언급 하나. 그 언급이 원본 기록(사건 연결표)과 맞는지만 본다. 값은 고치지 않는다.
규칙
- node_id는 노드표에 있고 attribute와 같은 단서여야 한다.
- SEX·REGION(환자 단위): 그 환자의 성별·지역 노드 자신이거나 그 상위여야 한다.
- 그 밖(사건 단위): event_id가 그 환자의 사건이고, node_id가 그 사건의 코드·나이·시작/종료 날짜 노드 자신이거나 상위여야 한다.
  (문서가 원본보다 넓게 말하는 것은 허용, 더 구체적이거나 다른 값은 불일치)
- 문서에 언급됐지만 사실표에 없는 단서는 이 검사로 못 잡는다 → 표본 사람 확인(명세 참조)."""
import csv, sys, json, collections
fact, nodes, events = sys.argv[1], sys.argv[2], sys.argv[3]
R = lambda p: list(csv.DictReader(open(p, encoding='utf-8-sig')))
N = {n['node_id']: n for n in R(nodes)}
E = {e['event_id']: e for e in R(events)}
pat = {}
for e in E.values(): pat[e['patient_id']] = (e['sex_node'], e['region_node'])
def anc(n):
    s = set()
    while n: s.add(n); n = N[n]['parent_id'] if n in N else ''
    return s
res, bad = collections.Counter(), []
for i, f in enumerate(R(fact), 2):
    a, nid, p, ev = f['attribute'], f['node_id'], f['patient_id'], f.get('event_id', '')
    why = None
    if nid not in N: why = 'NODE_NOT_FOUND'
    elif N[nid]['attribute'] != a: why = 'ATTRIBUTE_MISMATCH'
    elif a in ('SEX', 'REGION'):
        own = pat.get(p, ('', ''))[0 if a == 'SEX' else 1]
        if not own or nid not in anc(own): why = 'NOT_SUPPORTED_BY_PATIENT_RECORD'
    else:
        e = E.get(ev)
        if not e: why = 'EVENT_NOT_FOUND'
        elif e['patient_id'] != p: why = 'EVENT_OF_OTHER_PATIENT'
        else:
            own = set()
            for c in (e.get('code_nodes') or e['code_node']).split(';') + [e['age_node'], e['period_start_node'], e['period_end_node']]:
                if c: own |= anc(c)
            if nid not in own: why = 'NOT_SUPPORTED_BY_EVENT'
    res['ok' if not why else why] += 1
    if why: bad.append({'row': i, 'doc_id': f['doc_id'], 'span_text': f['span_text'], 'reason': why})
out = {'facts': sum(res.values()), 'result': dict(res), 'mismatches': bad[:200], 'status': 'PASS' if not bad else 'CHECK'}
s = json.dumps(out, ensure_ascii=False, indent=1)
if len(sys.argv) > 4: open(sys.argv[4], 'w', encoding='utf-8').write(s)
print(s)
