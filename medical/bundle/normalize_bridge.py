"""의료 확장 Observation → 정규화(노드·mapping_status) → k 계산기 입력 변환 (v0.11.1, 2026-10-21).

원설계 3/16(Extractor)·4/16(Normalizer)을 의료 6개 단서로 확장한다.
- Extractor 출력(LLM)은 이 파일 밖이다. 여기서는 Extractor가 낸 Observation을 받아 처리한다.
- 원설계 계승: evidence_spans 필수(3.11), Query에만 있는 값 금지(3.8), Extractor와 Normalizer 분리(3.15),
  mapping_status MAPPED/PENDING/UNMAPPED(C03), PENDING·UNMAPPED는 후보 제약에 넣지 않음(C04).
- 의료 확장(본 연구 설계): subject, context_status, event_ref, time_role.
- v0.9: MED(처방 기록, med_assertion 보존)·PLAN(관리 계획) 추가. 처방 예정·권고(PLANNED/RECOMMENDED)는 PENDING.
- v0.10: PERIOD 분기("2024년 1분기", "2024 Q1") → QUARTER 노드. 상·하반기 → 연, 순(초·중·하순)·'경' → 월.
- v0.9.1: subject 없으면 PENDING(기본값으로 TARGET_PATIENT 가정하지 않음), case_ref = UNCLEAR면 PENDING,
  min_confidence(τ_commit)를 주면 confidence < τ는 PENDING(값은 정답 세트로 결정, 미정 → 기본 None = 검사 안 함).
  별칭이 한 계통의 상·하위 노드 여럿에 걸리면(38개, 모두 DX) 가장 넓은 노드로 MAPPED.
"""
import csv, re, collections

ATTRS = {'AGE', 'SEX', 'REGION', 'DX', 'PROC', 'PERIOD', 'MED', 'PLAN'}   # v0.9: MED·PLAN
COMMIT_CONTEXT = {'CURRENT', 'HISTORY', 'DONE', 'UNSPECIFIED'}   # 실제 존재·시행한 사실
HOLD_CONTEXT = {'SUSPECTED', 'PLANNED', 'REQUESTED', 'RECOMMENDED'}            # 1차 미지원: 후보 제약에 넣지 않고 보류
DROP_CONTEXT = {'NEGATED'}                                      # 부정된 사실: 해당 값 보유 제약으로 쓰지 않음
ROLES = {'CONDITION_START', 'CONDITION_END', 'PROCEDURE_START', 'PROCEDURE_END', 'ENCOUNTER_START', 'ENCOUNTER_END',
         'MEDICATION_START', 'MEDICATION_END', 'CAREPLAN_START', 'CAREPLAN_END'}   # v0.9
MED_ASSERTION = {'PRESCRIBED', 'TAKING', 'ADMINISTERED'}  # v0.9 결정: 셋 다 처방 기록과 매칭, 원 표현은 med_assertion으로 보존

class Normalizer:
    def __init__(self, nodes_csv, alias_csv, min_confidence=None):
        self.min_confidence = min_confidence   # τ_commit (설계 3.12·5.9). None이면 confidence 검사 안 함
        self.node = {r['node_id']: r for r in csv.DictReader(open(nodes_csv, encoding='utf-8-sig'))}
        self.alias = collections.defaultdict(set)
        for r in csv.DictReader(open(alias_csv, encoding='utf-8-sig')):
            self.alias[(r['attribute'], r['surface_form'].strip().lower())].add(r['node_id'])
        # 도시만 말한 경우를 위한 색인: "Braintree, Massachusetts" → "braintree". 한 도시명이 여러 노드면 모호로 둔다
        self.city = collections.defaultdict(set)
        for (att, sf), nids in self.alias.items():
            if att == 'REGION' and ',' in sf:
                self.city[sf.split(',')[0].strip()] |= nids

    def _anc(self, n):
        out = set()
        while n: out.add(n); n = self.node[n]['parent_id']
        return out

    def _chain_top(self, hits):
        """hits가 모두 한 조상 경로 위에 있으면 가장 위(넓은) 노드, 아니면 None."""
        for h in hits:
            if all(h in self._anc(x) for x in hits): return h
        return None

    def _age(self, raw):
        s = raw.replace(' ', '')
        m = re.fullmatch(r'(\d{1,3})(세|살|years?old|y)?', s, re.I)
        if m: return f'AGE_Y{int(m.group(1))}'
        m = re.fullmatch(r'(\d{1,3})0대', s)
        if m: return f'AGE10_{int(m.group(1))*10}'
        m = re.fullmatch(r'(\d{1,3})[~\-](\d{1,3})(세|살)?', s)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a % 10 == 0 and b == a + 9: return f'AGE10_{a}'
            if a % 5 == 0 and b == a + 4: return f'AGE5_{a}'
        return None

    _QTR = re.compile(r'^(\d{4})\s*년?\s*[-\s]?\s*(?:([1-4])\s*분기|[Qq]([1-4]))$')
    _HALF = re.compile(r'^(\d{4})\s*년?\s*(상반기|하반기)$')

    def _period(self, raw, role):
        """v0.10: 분기는 QUARTER 노드로. 상·하반기는 연으로, 순(초·중·하순)·'경'은 월로 받는다
        (노드가 없는 단위는 그것을 감싸는 가장 좁은 노드로 — 실제보다 구체적으로 세지 않는다)."""
        self._period_note = None
        if role not in ROLES: return None, 'PENDING'
        basis = 'DATE' if role.startswith(('CONDITION', 'CAREPLAN')) else 'UTC'   # 진단·관리 계획은 날짜만, 시술·진료·처방은 UTC
        s = raw.strip()
        s = re.sub(r'\s*(경|쯤|무렵|즈음)$', '', s)
        s2 = re.sub(r'(\d{1,2})\s*월\s*(초순|중순|하순|상순|초반|중반|후반|초|중|말)$', r'\1월', s)
        if s2 != s: self._period_note = 'SUB_MONTH_TO_MONTH'; s = s2
        m = self._QTR.match(s)
        if m:
            nid = f'PERIOD_{role}_{basis}_QUARTER_{m.group(1)}-Q{m.group(2) or m.group(3)}'
            return (nid, 'MAPPED') if nid in self.node else (None, 'UNMAPPED')
        m = self._HALF.match(s)
        if m: s = m.group(1); self._period_note = 'HALF_YEAR_TO_YEAR'
        s = s.replace('년', '-').replace('월', '').replace('일', '').replace(' ', '').rstrip('-')
        m = re.fullmatch(r'(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?', s)
        if not m: return None, 'UNMAPPED'
        y, mo, d = m.groups()
        if d: nid = f'PERIOD_{role}_{basis}_DAY_{y}-{int(mo):02d}-{int(d):02d}'
        elif mo: nid = f'PERIOD_{role}_{basis}_MONTH_{y}-{int(mo):02d}'
        else: nid = f'PERIOD_{role}_{basis}_YEAR_{y}'
        return (nid, 'MAPPED') if nid in self.node else (None, 'UNMAPPED')

    # ---- v0.11.1 표현 다듬기 ------------------------------------------------------------------
    # AI가 기록의 표기에 군더더기를 붙여 말할 때를 받는다. 원칙: 다듬은 꼴이 별칭표에 **정확히** 있을 때만 받는다.
    # 느슨한 유사 매칭은 하지 않는다(없는 공개를 만들어내면 k가 실제보다 작아진다).
    # 다듬은 경우 reasons에 어떤 변형을 썼는지 남겨 사람이 되짚을 수 있게 한다.
    _JOSA = ('에서', '으로', '은', '는', '이', '가', '을', '를', '에', '로', '와', '과', '의', '도')
    _REGION_SUFFIX = ('주', '시', '군', '구', '현', '성')     # "Massachusetts 주" 같은 한국어 행정단위 접미사
    def _variants(self, att, raw):
        """원표현 → 시도할 꼴들을 (꼴, 변형이름)으로 내놓는다. 원표현이 먼저다."""
        s = raw.strip()
        yield s, ''
        m = re.match(r'^(.*?)\s*[（(]\s*([^()（）]+?)\s*[)）]\s*$', s)    # "심근경색(Myocardial infarction)"
        if m:
            for g in (m.group(2), m.group(1)):                          # 괄호 안(원어)을 먼저 본다
                if g.strip(): yield g.strip(), 'PAREN_SPLIT'
        for j in self._JOSA:                                            # 뒤에 붙은 조사
            if s.endswith(j) and len(s) > len(j) + 1: yield s[:-len(j)].strip(), 'JOSA_STRIPPED'
        if att == 'REGION':
            for suf in self._REGION_SUFFIX:                             # "Massachusetts 주"
                if s.endswith(suf) and len(s) > len(suf) + 1: yield s[:-len(suf)].strip().rstrip(','), 'REGION_SUFFIX_STRIPPED'
    def _lookup(self, att, raw):
        """별칭표에서 찾는다. 원표현이 안 되면 다듬은 꼴을 차례로 본다. 반환 (후보 노드들, 변형이름)."""
        for cand, how in self._variants(att, raw):
            hits = self.alias.get((att, cand.lower()), set())
            if hits: return hits, how
        if att == 'REGION':                                             # "Braintree"처럼 도시만 말한 경우
            hits = self.city.get(raw.strip().lower(), set())
            if len(hits) == 1: return hits, 'CITY_ONLY'
            if hits: return hits, 'CITY_ONLY_AMBIGUOUS'                 # 여러 주에 같은 도시명 → AMBIGUOUS_ALIAS로 PENDING
        return set(), ''

    def normalize(self, ob, response_text, query_text=''):
        out = dict(ob); out['node_id'] = None; out['commit'] = False; out['reasons'] = []
        att, raw = ob.get('attribute'), str(ob.get('raw_value', ''))
        spans = ob.get('evidence_spans') or []
        if att not in ATTRS: out['mapping_status'] = 'UNMAPPED'; out['reasons'].append('OUT_OF_SCOPE_ATTRIBUTE'); return out
        if not spans or not all(sp in response_text for sp in spans):
            out['mapping_status'] = 'PENDING'; out['reasons'].append('EVIDENCE_NOT_IN_RESPONSE (3.8, 3.11)'); return out
        if ob.get('subject') is None:
            out['mapping_status'] = 'PENDING'; out['reasons'].append('SUBJECT_MISSING'); return out
        if ob['subject'] != 'TARGET_PATIENT':
            out['mapping_status'] = 'PENDING'; out['reasons'].append('SUBJECT_NOT_TARGET (C09)'); return out
        if ob.get('case_ref') == 'UNCLEAR':
            out['mapping_status'] = 'PENDING'; out['reasons'].append('CASE_UNCLEAR'); return out
        if self.min_confidence is not None and int(ob.get('confidence') or 0) < self.min_confidence:
            out['mapping_status'] = 'PENDING'; out['reasons'].append('LOW_CONFIDENCE (3.12)'); return out
        ctx = ob.get('context_status', 'UNSPECIFIED')
        if att == 'MED':   # v0.9: 처방·복용·투여 표현 모두 처방 사실로 매칭(실제 복용은 데이터로 확인 불가)
            out['med_assertion'] = ob.get('med_assertion', 'UNSPECIFIED')
        if att in ('DX', 'PROC', 'MED', 'PLAN'):
            if ctx in DROP_CONTEXT: out['mapping_status'] = 'PENDING'; out['reasons'].append('NEGATED'); return out
            if ctx in HOLD_CONTEXT: out['mapping_status'] = 'PENDING'; out['reasons'].append(f'CONTEXT_{ctx}_NOT_SUPPORTED_1ST (R2)'); return out
        if att == 'AGE': nid = self._age(raw); st = 'MAPPED' if nid in self.node else 'UNMAPPED'
        elif att == 'PERIOD':
            nid, st = self._period(raw, ob.get('time_role'))
            if getattr(self, '_period_note', None): out['reasons'].append(self._period_note)
        else:
            hits, used = self._lookup(att, raw)
            if used: out['reasons'].append(used)
            top = self._chain_top(hits) if len(hits) > 1 else None
            if top:   # 같은 이름이 한 계통의 상·하위 노드에 함께 있으면(예: SNOMED 진단과 같은 이름의 ICD 범주) 가장 넓은 노드로 = 구체성을 부풀리지 않음
                nid, st = top, 'MAPPED'; out['reasons'].append('ALIAS_CHAIN_MOST_GENERAL')
            else:
                nid, st = (next(iter(hits)), 'MAPPED') if len(hits) == 1 else (None, 'PENDING' if hits else 'UNMAPPED')
                if len(hits) > 1: out['reasons'].append('AMBIGUOUS_ALIAS')
        out['node_id'], out['mapping_status'] = (nid if st == 'MAPPED' else None), st
        out['commit'] = st == 'MAPPED'
        if st != 'MAPPED': out['reasons'].append(f'{st} (C04: 후보 제약 제외)')
        return out

def to_disclosures(normalized, turn_prefix=True):
    """commit된 Observation → kcalc 입력. event_ref가 있으면 같은 사건 묶음(event_group)으로 넘긴다."""
    ds, partial = [], False
    for o in normalized:
        if not o['commit']:
            partial = partial or o['attribute'] in ATTRS; continue
        g = o.get('event_ref')
        ds.append({'attribute': o['attribute'], 'node_id': o['node_id'], 'event_group': g})
    return ds, partial
