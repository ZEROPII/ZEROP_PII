import { describe, expect, it } from 'vitest';
import { changesByCase } from '../components/clinic/ClinicalMessage';
import type { PrivacyTransformation, ProtectionResult } from '../types/domain';

const t = (o: Partial<PrivacyTransformation>): PrivacyTransformation => ({
  id: Math.random().toString(36).slice(2),
  attribute: 'MED',
  attributeLabel: '처방 약',
  action: 'suppress',
  disclosedValue: null,
  ...o,
});

describe('답 아래 사례마다 바뀐 항목 (ADR-0037)', () => {
  it('사례마다 비공개 · 범위 항목 이름만 (몇 개인지는 세지 않는다), 그대로 둔 값은 뺀다', () => {
    const p = {
      transformations: [
        t({ caseRef: '사례2', attribute: 'PERIOD', attributeLabel: '시기', action: 'generalize' }),
        t({ caseRef: '사례1' }),
        t({ caseRef: '사례1' }),
        t({ caseRef: '사례1', attribute: 'PLAN', attributeLabel: '관리 계획' }),
        t({ caseRef: '사례1', attribute: 'DURATION', attributeLabel: '사례 1 기간', action: 'generalize' }),
        t({ caseRef: '사례3', action: 'allow' }),
        t({ caseRef: '사례10', dropped: true }),
      ],
    } as unknown as ProtectionResult;
    expect(changesByCase(p)).toEqual([
      { ref: '사례1', hidden: ['처방 약', '관리 계획'], ranged: ['기간'], dropped: false },
      { ref: '사례2', hidden: [], ranged: ['시기'], dropped: false },
      { ref: '사례10', hidden: [], ranged: [], dropped: true },
    ]);
  });
});
