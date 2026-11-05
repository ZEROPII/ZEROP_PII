// 의료진 화면 보조 계산: 요청 상태 · 찾은 사례 한눈에 · 한국어 진단 찾기 · 진료 기록 복사 · 조회 목적 문구.
import { describe, expect, it } from 'vitest';
import type { CaseSummary, ClinicMessage, ProtectionResult } from '../types/domain';
import { matchReasons, overviewOf, splitItem } from './caseOverview';
import { answerPlainText, chartCopyText, protectionNote, whyText } from './clinicianCopy';
import { koreanNames } from './koTerms';
import { latestRequest, statusOf } from './requests';

const msg = (over: Partial<ClinicMessage>): ClinicMessage => ({
  messageId: `m-${Math.random()}`,
  createdAt: '2026-11-05T10:00:00Z',
  sender: 'clinician',
  kind: 'access_request',
  kindLabel: '세부 정보 요청',
  caseId: 'case-1',
  caseLabel: '사례 1',
  text: '사례 1 시기 세부 정보가 필요합니다.',
  ...over,
});

describe('세부 정보 요청 상태', () => {
  it('요청 뒤 같은 사례의 공개 승인이 있으면 승인, 답장만 있으면 답장 옴, 없으면 대기 중', () => {
    const req = msg({});
    expect(statusOf([req], req).state).toBe('pending');
    const reply = msg({ sender: 'security', kind: 'reply', createdAt: '2026-11-05T10:05:00Z' });
    expect(statusOf([req, reply], req)).toMatchObject({ state: 'answered', doneAt: '2026-11-05T10:05:00Z' });
    const rel = msg({ sender: 'security', kind: 'release', createdAt: '2026-11-05T10:06:00Z' });
    expect(statusOf([req, reply, rel], req).state).toBe('released');
    // 다른 사례의 승인은 이 요청과 상관없다
    const other = msg({ sender: 'security', kind: 'release', caseId: 'case-2' });
    expect(statusOf([req, other], req).state).toBe('pending');
  });

  it('답 뒤에 보낸 요청만 그 답의 요청으로 본다', () => {
    const old = msg({ createdAt: '2026-11-05T09:00:00Z' });
    expect(latestRequest([old], 'case-1', '2026-11-05T09:30:00Z')).toBeNull();
    expect(latestRequest([old], 'case-1', '')?.state).toBe('pending');
    // 다음 질문 뒤에 보낸 요청은 그 다음 답의 요청이다
    expect(latestRequest([old], 'case-1', '2026-11-05T08:00:00Z', '2026-11-05T08:30:00Z')).toBeNull();
  });
});

const c = (n: number, diagnosis: string, description: string): CaseSummary => ({ caseId: `case-${n}`, label: `사례 ${n}`, diagnosis, description, similarityRank: n });

describe('찾은 사례 한눈에', () => {
  const cases = [
    c(1, 'Acute bronchitis', '처방 약 acetaminophen 325 MG Oral Tablet'),
    c(2, 'Acute bronchitis', '처방 약 acetaminophen 325 MG Oral Tablet'),
    c(3, 'Acute pharyngitis', '처방 약 (비공개)'),
    c(4, 'Acute bronchitis', '처방 약 sodium fluoride 0.0272 MG/MG Oral Gel'),
  ];
  it('사례 목록에 보이는 값만 세고, 비공개 값은 세지 않는다', () => {
    const o = overviewOf(cases);
    expect(o.total).toBe(4);
    expect(o.commonDx).toBe('Acute bronchitis');
    expect(o.diagnoses[0]).toEqual({ value: 'Acute bronchitis', n: 3 });
    expect(o.commonItem).toBe('처방 약 acetaminophen 325 MG Oral Tablet');
    expect(o.items.some((x) => x.value.includes('비공개'))).toBe(false);
    expect(splitItem(o.commonItem!)).toEqual(['처방 약', 'acetaminophen 325 MG Oral Tablet']);
  });
  it('지금 환자와 겹치는 점은 환자 띠의 주진단 · 고려 중 처치와만 비교한다', () => {
    expect(matchReasons(cases[0], { primaryDiagnosis: 'Acute bronchitis', plannedProcedure: 'acetaminophen' })).toEqual(['주진단 같음', '고려 중 처치와 같음']);
    expect(matchReasons(cases[2], { primaryDiagnosis: 'Acute bronchitis', plannedProcedure: 'acetaminophen' })).toEqual([]);
    expect(matchReasons(cases[0], null)).toEqual([]);
  });
});

describe('한국어 진단 찾기', () => {
  it('영어 진단 이름에 한국어 이름을 잇는다', () => {
    expect(koreanNames('Acute bronchitis')).toContain('기관지염');
    expect(koreanNames('Gingivitis and periodontal diseases')).toContain('치은염');
    expect(koreanNames('Essential (primary) hypertension')).toContain('고혈압');
    expect(koreanNames('Chronic sinusitis, unspecified')).toContain('축농증');
    expect(koreanNames('Unknown thing')).toBe('');
  });
});

describe('진료 기록 복사와 조회 목적 문구', () => {
  it('출처 머리를 붙이고, 보호한 값이 있으면 꼬리를 붙인다', () => {
    expect(chartCopyText('사례1 환자는 X를 처방받았습니다.', '사례 1')).toBe('[진료 지원 AI · 유사 사례 참고 · 사례 1]\n사례1 환자는 X를 처방받았습니다.');
    expect(chartCopyText('답', '사례 1', { all: true, protectedCount: 2 })).toContain('찾은 사례 전체');
    expect(chartCopyText('답', '사례 1', { protectedCount: 1 })).toContain('MediCloak');
  });
  it('조회 목적으로 뺀 값은 위험 때문이라고 말하지 않는다', () => {
    const p: ProtectionResult = {
      decision: 'suppress',
      transformations: [{ id: 't1', attribute: 'REGION', attributeLabel: '사례 1 거주 지역', action: 'suppress', disclosedValue: null, caseRef: '사례1', purpose: true }],
      explanation: null,
      kBefore: null,
      kAfter: null,
      releaseMode: 'REWRITTEN',
    };
    expect(protectionNote(p)?.text).toBe('이번 조회 목적에 필요하지 않은 정보는 답에서 뺐습니다.');
    const why = whyText(p, '사례 1');
    expect(why[0]).toContain('조회 목적');
    expect(why.join(' ')).not.toContain('환자가 아주 적어');
  });
});

describe('지워진 가린 값의 자리 표시', () => {
  it('진료 기록 복사에도 무엇을 가렸는지 남긴다', () => {
    const tf = [
      { id: 't1', attribute: 'PERIOD', attributeLabel: '사례 1 시기', action: 'suppress', disclosedValue: null, levelDescription: '가림', caseRef: '사례1' },
      { id: 't2', attribute: 'AGE', attributeLabel: '사례 1 나이', action: 'generalize', disclosedValue: '40~44세', levelDescription: '범위', caseRef: '사례1' },
    ] as unknown as ProtectionResult['transformations'];
    const text = answerPlainText(
      [
        { kind: 'text', text: '사례1은 ' },
        { kind: 'disclosure', text: '40~44세', transformationId: 't2' },
        { kind: 'text', text: '였고 약을 처방받았습니다.' },
        { kind: 'disclosure', text: '(비공개)', transformationId: 't1', placeholder: true, label: '시기' },
      ],
      tf,
    );
    expect(text).toBe('사례1은 40~44세 (범위)였고 약을 처방받았습니다. (시기 비공개)');
  });
});
