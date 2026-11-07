"""1차 측정용 누적 후보 수(k) 계산기 (v0.9.1, 2026-10-09).

근거 규칙 (C코드 뜻은 대상AI_하네스_평가_명세 부록 A):
- 후보 = 조건을 만족하는 고유 환자 (C10, Samarati 2001 k 정의)
- 같은 단서·같은 사건 묶음에서 하위 노드가 오면 세분화로 갱신, 상위·같은 노드는 기존 유지 (C07)
- 같은 단서·같은 묶음에서 양립 불가(트리상 상하위 아님)이면 충돌로 격리, 계산 제외 (C08). 단 DX·PROC는 한 사건에 여러 코드가 공존하므로(ICD 다중 코딩, I-MAGIC p.8) 추가 조건으로 본다
- 등록부에 없는 값은 계산에서 빼고 부분 평가로 표시 (C04, C05, DX R7)
- 사건 묶음(event_group)이 같은 사건 단위 단서는 한 사건이 함께 만족 (C09, C10)
- 묶음이 없는 사건 단위 단서: 같은 사건 해석과 따로 해석을 모두 계산, k>0인 해석 중 작은 값으로 판정, AMBIGUOUS 표시
- 모든 해석이 0이면 ZERO_MATCH (k=0을 가장 위험한 상태로 보지 않음, 원설계 6.26–6.27)
SEX·REGION은 환자 단위, AGE(사건 당시)·DX·PROC·PERIOD·MED·PLAN은 사건 단위 (v0.9: MED·PLAN 추가, 한 진료에 여러 개 가능 → 다중값).
v0.9.1: 같은 사건 묶음의 PERIOD는 역할(시작/종료 등)별로 따로 둔다(이전에는 시작·종료가 CONFLICT로 버려짐).
v0.9.1: exclude_provisional_atc=True면 ATC 근거 등급 '잠정' 연결(review_status에 '(잠정)')을 끊고 그 약을 ANY_MED 바로 아래로 본다(민감도 분석용).
"""
import csv, collections

PATIENT_LEVEL = {'SEX': 'sex_node', 'REGION': 'region_node'}
EVENT_LEVEL = {'AGE', 'DX', 'PROC', 'PERIOD', 'MED', 'PLAN'}   # v0.9: 약물(처방)·관리 계획 추가
MULTI_VALUED = {'DX', 'PROC', 'MED', 'PLAN'}  # 한 사건에 여러 값이 공존 가능: 상하위가 아니면 충돌이 아니라 추가 조건

class KCalc:
    def __init__(self, nodes_csv, events_csv, exclude_provisional_atc=False, patients=None):
        """patients: 참조 모집단(P_ref)으로 쓸 patient_id 집합. None이면 사건표 전체. 실험에서는 RAG 저장소(STORE) 환자만 넘긴다."""
        self.node = {r['node_id']: r for r in csv.DictReader(open(nodes_csv, encoding='utf-8-sig'))}
        self.exclude_provisional_atc = exclude_provisional_atc
        self._anc = {}
        self.events = [e for e in csv.DictReader(open(events_csv, encoding='utf-8-sig')) if patients is None or e['patient_id'] in patients]
        self.ev_anc = []
        self.pat = {}
        for e in self.events:
            s = set()
            codes = (e.get('code_nodes') or e['code_node']).split(';')  # v0.7: 한 사건에 ICD 코드 여러 개 가능
            for c in codes + [e['age_node'], e['period_start_node'], e['period_end_node']]:
                if c: s |= self.anc(c)
            self.ev_anc.append(s)
            self.pat[e['patient_id']] = {'SEX': self.anc(e['sex_node']), 'REGION': self.anc(e['region_node']) if e['region_node'] else set()}
        self.by_pat = collections.defaultdict(list)
        for i, e in enumerate(self.events): self.by_pat[e['patient_id']].append(i)

    def anc(self, nid):
        if nid in self._anc: return self._anc[nid]
        out, x = set(), nid
        while x:
            out.add(x)
            n = self.node[x]
            if self.exclude_provisional_atc and n['attribute'] == 'MED' and '(잠정)' in n['review_status']:
                x = 'ANY_MED' if x != 'ANY_MED' else None; continue   # 잠정 ATC 연결을 끊음
            x = n['parent_id'] or None
        self._anc[nid] = out
        return out

    def reduce(self, disclosures):
        """C07/C08 + 규칙 2: 같은 단서 안에서 세분화·유지·충돌·별개 사실 처리."""
        state, flags, conflicts, unsupported, n_loose = {}, [], [], [], 0
        for d in disclosures:
            att, nid, g = d['attribute'], d['node_id'], d.get('event_group')
            if nid not in self.node or self.node[nid]['attribute'] != att:
                unsupported.append(d); continue
            if att in PATIENT_LEVEL: cands = [(att,)]
            elif g is not None and att in MULTI_VALUED: cands = [k for k in state if k[0] == att and k[1] == g]
            elif g is not None and att == 'PERIOD': cands = [(att, g, self.node[nid]['time_role'])]   # v0.9.1: 같은 사건의 시작일·종료일은 별개 값(충돌 아님)
            elif g is not None: cands = [(att, g)]
            else: cands = [k for k in state if k[0] == att and k[1] is None]
            hit = None
            for key in cands:
                if key not in state: continue
                cur = state[key]
                if cur in self.anc(nid) or nid in self.anc(cur): hit = key; break
            if hit is not None:
                cur = state[hit]
                if cur in self.anc(nid) and cur != nid: state[hit] = nid; flags.append(f'REFINED {cur}->{nid}')
                else: flags.append(f'KEPT {cur} (new {nid} is same/ancestor)')
            elif g is not None and att in MULTI_VALUED:
                n_loose += 1; state[(att, g, n_loose)] = nid  # 한 사건에 진단·시술 여러 개 가능(ICD 다중 코딩)
            elif att in PATIENT_LEVEL or g is not None:
                key = cands[0]
                if key in state:
                    conflicts.append(key); flags.append(f'CONFLICT {state[key]} vs {nid}')
                else: state[key] = nid
            else:
                n_loose += 1; state[(att, None, n_loose)] = nid  # 상하위 아닌 별개 사실
        for key in set(conflicts): state.pop(key, None)
        if unsupported: flags.append('PARTIAL: unsupported disclosure excluded')
        return state, flags, conflicts, unsupported

    def _patients(self, patient_conds, groups):
        """patient_conds: [(att,node)], groups: list of lists of event-level nodes (각 묶음은 한 사건이 모두 만족)."""
        out = set()
        for p, evs in self.by_pat.items():
            pa = self.pat[p]
            if any(n not in pa[a] for a, n in patient_conds): continue
            if all(any(all(n in self.ev_anc[i] for n in grp) for i in evs) for grp in groups):
                out.add(p)
        return out

    def candidates(self, disclosures):
        """k와 같은 판정으로 고른 해석의 후보 환자 집합(평가용: Validated k에서 사례 환자가 후보 안에 있는지 확인)."""
        return self._eval(disclosures)[1]

    def k(self, disclosures):
        return self._eval(disclosures)[0]

    def _eval(self, disclosures):
        state, flags, conflicts, unsupported = self.reduce(disclosures)
        pconds = [(k[0], v) for k, v in state.items() if k[0] in PATIENT_LEVEL]
        grouped = collections.defaultdict(list); loose = []
        for k, v in state.items():
            if k[0] in EVENT_LEVEL:
                (grouped[k[1]].append(v) if k[1] is not None else loose.append(v))
        base_groups = list(grouped.values())
        sets = {}
        if len(loose) == 1:
            base_groups.append(loose); loose = []
        if loose:
            sets['same_event'] = self._patients(pconds, base_groups + [loose])
            sets['separate'] = self._patients(pconds, base_groups + [[n] for n in loose])
            flags.append('AMBIGUOUS: ungrouped event-level disclosures')
        else:
            sets['grouped'] = self._patients(pconds, base_groups)
        interp = {k: len(v) for k, v in sets.items()}
        pos = [k for k, v in interp.items() if v > 0]
        chosen = min(pos, key=lambda k: interp[k]) if pos else None
        decision = interp[chosen] if chosen else 0
        if not pos: flags.append('ZERO_MATCH')
        res = {'k': decision, 'interpretations': interp, 'flags': flags, 'state': {str(k): v for k, v in state.items()}}
        return res, (sets[chosen] if chosen else set())
