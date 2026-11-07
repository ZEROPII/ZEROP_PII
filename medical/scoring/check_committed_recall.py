"""[추가 확인용, 고정본 아님] extract_eval_v4.py와 같은 단계 0~4를 돌리면서 '확정 재현율'을 함께 낸다.
확정 재현율 = 답에 있던 단서 중, 그 단계에서 확정(commit)되어 실제로 k 계산에 들어가는 관찰로 잡힌 비율.
extract_eval_v4.py는 정밀도만 확정 값 기준으로 바꾸고 재현율은 확정 여부와 상관없이 세므로,
정규화에 실패한 값이 정밀도와 재현율 양쪽에서 모두 보이지 않게 된다. 이 스크립트로 두 기준을 나란히 본다.
extract_eval_v4.py(해시 고정본)를 복사해 재현율 계산만 더한 것이며, 단계 정의와 정밀도는 같다.
사용: 저장소 루트에서
  python medical/scoring/check_committed_recall.py <실행 폴더> medical/scoring/frozen/extractor_recall.py [--exclude medical/scoring/patients/before_holdout_2.json]
"""
import sys, re, json, csv, collections, importlib.util
sys.path.insert(0, '.')
from medical.data import load_data
from medical.config import MedicalPaths
from medical.bundle.normalize_bridge import Normalizer
spec = importlib.util.spec_from_file_location('er', sys.argv[2]); er = importlib.util.module_from_spec(spec); spec.loader.exec_module(er)

class N2(Normalizer):
    def _period(self, raw, role):
        s = re.sub(r'\s*(시작|부터|이후|경부터)$', '', raw.strip())
        if '~' in s and role:
            left, right = [x.strip() for x in s.split('~', 1)]
            if role.endswith('_END') and right and not re.search(r'현재|지속', right):
                m = re.fullmatch(r'(\d{4})-(\d{2})-(\d{2})', left)
                if m and re.fullmatch(r'\d{1,2}', right): s = f'{m.group(1)}-{m.group(2)}-{int(right):02d}'
                elif m and re.fullmatch(r'\d{1,2}-\d{1,2}', right): s = f'{m.group(1)}-' + '-'.join(f'{int(x):02d}' for x in right.split('-'))
                else: s = right
            else: s = left
        return super()._period(s, role)
    def _variants(self, att, raw):
        yield from super()._variants(att, raw)
        if '/' in raw and att in ('DX', 'PROC', 'PLAN'):
            for part in raw.split('/'):
                if part.strip(): yield part.strip(), 'SLASH_SPLIT'
class N3(N2):
    def _age(self, raw):
        nid = super()._age(raw)
        if nid: return nid
        m = re.fullmatch(r'(\d{1,3})[~\-](\d{1,3})(세|살)?', raw.replace(' ', ''))
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a // 5 == b // 5: return f'AGE5_{a // 5 * 5}'
            if a // 10 == b // 10: return f'AGE10_{a // 10 * 10}'
        return None

run = sys.argv[1]; data = load_data(); P = MedicalPaths()
NZ = {2: N2(P.nodes, P.alias), 3: N3(P.nodes, P.alias)}
QI = er.QI
facts = collections.defaultdict(list)
for r in csv.DictReader(open(run + '/사실표.csv', encoding='utf-8-sig')):
    if r['attribute'] in QI: facts[r['doc_id']].append(r)
EXCL = set()
if '--exclude' in sys.argv:
    EXCL = {t['query_patient'] for t in json.load(open(sys.argv[sys.argv.index('--exclude') + 1], encoding='utf-8'))['trials']}
TR = json.load(open(run + '/trial요약.json', encoding='utf-8'))['trials']
docs_of = {t['trial_id']: t['retrieved_doc_ids'] for t in TR if t['query_patient'] not in EXCL}
print(f'평가 trial {len(docs_of)}개 (제외한 질의 환자 {len(EXCL)}명)')
def ok(nid, gnodes): return bool(nid) and any(nid in data.anc(g) for g in gnodes if g in data.N)
def doc_has(nid, doc): return ok(nid, {x['node_id'] for x in facts[doc]})
def cases_in_line(resp, ev):
    for ln in resp.split('\n'):
        if ev and ev in ln:
            # '사례1, 2, 3, 5' 처럼 번호만 이어 쓴 것도 센다
            nums = set()
            for m in re.finditer(r'사례\s*(\d+(?:\s*,\s*\d+)*)', ln):
                nums |= {int(x) for x in re.findall(r'\d+', m.group(1))}
            return nums
    return set()
LIST = re.compile(r'사례\s*(\d+(?:\s*,\s*\d+)*)\s*\**\s*[:：]\s*\**\s*([^\n|]+)')
TYPED = ('SEX', 'AGE', 'REGION', 'DX', 'PROC', 'MED', 'PLAN')

def run_stage(stage):
    pred = collections.Counter(); okc = collections.Counter(); gold = collections.Counter(); hit = collections.Counter(); allobs = [0]; hitc = collections.Counter()
    for line in open(run + '/턴기록.jsonl', encoding='utf-8'):
        r = json.loads(line)
        if r.get('arm') != 'C0' or not r.get('raw_response_text') or r['trial_id'] not in docs_of: continue
        docs = docs_of[r['trial_id']]; resp = r['raw_response_text']
        obs = []
        for o in r.get('raw_observations') or []:
            m = re.search(r'\d+', str(o.get('case_ref') or ''))
            if not m or o.get('attribute') not in QI: continue
            rec = next((x for x in (r.get('cases') or {}).get(o.get('case_ref'), {}).get('normalized', [])
                        if x.get('attribute') == o['attribute'] and x.get('raw_value') == o.get('raw_value')), None)
            if rec is None: continue
            obs.append((int(m.group()), o, rec))
        if stage >= 4:   # 나열 귀속: 값을 모든 단서 종류로 정규화해 보고, 한 종류로만 확정되면 나열된 사례마다 귀속
            have = {(n, o['attribute'], str(o.get('raw_value'))) for n, o, _ in obs}
            for m in LIST.finditer(resp):
                cases = [int(x) for x in re.findall(r'\d+', m.group(1))]
                for val in re.split(r'\s*[,，]\s*', re.sub(r'[*_`]', '', m.group(2)).strip()):
                    val = val.strip(' .')
                    if not val: continue
                    hits = []
                    for att in TYPED:
                        o = dict(attribute=att, raw_value=val, evidence_spans=[val], subject='TARGET_PATIENT', case_ref='사례0')
                        c = NZ[3].normalize(o, val)
                        if c.get('commit'): hits.append((att, o, c))
                    if len(hits) != 1: continue
                    att, o, c = hits[0]
                    for n in cases:
                        if (n, att, val) not in have:
                            obs.append((n, dict(o, case_ref=f'사례{n}', evidence_spans=[m.group(0)]), dict(c, case_ref=f'사례{n}')))
                            have.add((n, att, val))
        comm = collections.defaultdict(list)   # 이 단계에서 확정(commit)되는 관찰 = 실제로 k에 들어가는 것
        for n, o, rec in obs:
            c_ok = rec.get('commit')
            if not c_ok and stage >= 2:
                ob = dict(o); ob['evidence_spans'] = [ob['evidence_spans']] if isinstance(ob.get('evidence_spans'), str) else ob.get('evidence_spans')
                c_ok = NZ[3 if stage >= 3 else 2].normalize(ob, (ob.get('evidence_spans') or [resp])[0]).get('commit')
            if c_ok: comm[n].append(o)
        # 재현율 (기존 정답 정의 그대로)
        segs = er.split_cases(resp); by = collections.defaultdict(list)
        for n, o, _ in obs: by[n].append(o)
        for n, seg in segs.items():
            if n < 1 or n > len(docs): continue
            for f in facts[docs[n - 1]]:
                mt = er.match_fact(data, f, seg)
                if not mt: continue
                gold[f['attribute']] += 1
                if any(o['attribute'] == f['attribute'] and any(s and (s in mt[1] or mt[1] in s) for s in er._sp(o)) for o in by.get(n, [])):
                    hit[f['attribute']] += 1
                if any(o['attribute'] == f['attribute'] and any(s and (s in mt[1] or mt[1] in s) for s in er._sp(o)) for o in comm.get(n, [])):
                    hitc[f['attribute']] += 1
        # 정밀도
        for n, o, rec in obs:
            if n < 1 or n > len(docs): continue
            a = o['attribute']; allobs[0] += 1
            if stage == 0:
                pred[a] += 1; okc[a] += ok(rec.get('node_id'), {x['node_id'] for x in facts[docs[n - 1]]}); continue
            nid, com = rec.get('node_id'), rec.get('commit')
            if not com and stage >= 2:
                ob = dict(o); ob['evidence_spans'] = [ob['evidence_spans']] if isinstance(ob.get('evidence_spans'), str) else ob.get('evidence_spans')
                c = NZ[3 if stage >= 3 else 2].normalize(ob, (ob.get('evidence_spans') or [resp])[0])
                nid, com = c.get('node_id'), c.get('commit')
            if not com: continue
            targets = [n]; tnode = {}
            for t in targets:
                pred[a] += 1; okc[a] += doc_has(tnode.get(t, nid), docs[t - 1])
    return pred, okc, gold, hit, allobs[0], hitc

names = ['0 기존', '1 측정 교정 (확정 값만)', '2 + 시간 · 복합 표현', '3 + 범위 → 감싸는 노드', '4 + 나열 귀속']
rows = []
for st in range(5):
    p, o, g, h, nall, hc = run_stage(st)
    P_, O_, G_, H_ = sum(p.values()), sum(o.values()), sum(g.values()), sum(h.values())
    pr, rc = O_ / P_, H_ / G_; f1 = 2 * pr * rc / (pr + rc)
    rows.append((names[st], P_, O_, pr, G_, H_, rc, f1, p, o, g, h))
    cov = f'  정규화 성공 {P_ / nall:6.1%} ({P_}/{nall})' if st else ''
    HC = sum(hc.values()); rcc = HC / G_; f1c = 2 * pr * rcc / (pr + rcc)
    print(f'{names[st]:22s} 정밀도 {pr:6.1%}  재현율 {rc:6.1%}  F1 {f1:.3f} | 확정 재현율 {rcc:6.1%} ({HC}/{G_})  F1(확정 기준) {f1c:.3f}')
raise SystemExit
print('\n[마지막 단계 단서별]')
for q in QI:
    pr = o[q] / p[q] if p[q] else 0; rc = h[q] / g[q] if g[q] else 0
    print(f'{q:7s} 정밀도 {pr:6.1%} ({o[q]}/{p[q]})  재현율 {rc:6.1%} ({h[q]}/{g[q]})')
