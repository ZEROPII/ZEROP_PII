// 의료진 화면 문구. 후보 수·기준값 같은 재식별 위험 숫자는 쓰지 않는다 (그 숫자는 보안 담당자 화면에만 있다).
// 무엇이 어떻게 보이는지(범위 · 비공개), 왜 그런지, 필요하면 어떻게 요청하는지만 쉬운 말로 알린다.

import type { PreflightRiskAssessment, PrivacyTransformation, ProtectionResult } from '../types/domain';
import { josa } from './korean';

/** QI 코드 → 의료진 화면 이름 (webdemo clinic.py ATTR_LABEL과 같다). 모르는 코드는 백엔드 이름을 쓴다. */
export const ATTR_LABEL: Record<string, string> = {
  AGE: '나이',
  SEX: '성별',
  REGION: '거주 지역',
  DX: '진단',
  PROC: '시술',
  PERIOD: '시기',
  MED: '처방 약',
  PLAN: '관리 계획',
};

/** 조치 하나의 항목 이름. 데모 백엔드는 attributeLabel에 '사례 1 '을 붙여 보내므로 떼어 낸다. */
export function attrName(t: Pick<PrivacyTransformation, 'attribute' | 'attributeLabel'>): string {
  return ATTR_LABEL[t.attribute] ?? t.attributeLabel.replace(/^사례\s*\S+\s+/, '');
}

/** '사례1' → '사례 1' */
export function refLabel(ref: string): string {
  return ref.replace(/^사례\s*(\S+)$/, '사례 $1');
}

function joinNames(names: string[]): string {
  return [...new Set(names.filter(Boolean))].join(', ');
}

export interface Notice {
  tone: 'lock' | 'range' | 'info';
  text: string;
}

/** 보내기 전 안내. 보내면 어떻게 답할지만 말한다. 안내할 것이 없으면 null. */
export function preflightNotice(a: PreflightRiskAssessment, caseLabel: string): Notice | null {
  if (!a.requiresWarning) return null;
  const names = joinNames(a.affectedAttributes);
  const what = names ? `${caseLabel}의 ${josa(names, '은', '는')}` : `${caseLabel} 답의 일부는`;
  if (a.plannedAction === 'suppress')
    return { tone: 'lock', text: `이 질문에 답하면 ${what} 비공개로 표시됩니다. 나머지 내용은 그대로 답합니다.` };
  if (a.plannedAction === 'generalize')
    return { tone: 'range', text: `이 질문에 답하면 ${what} 정확한 값 대신 범위로 표시됩니다.` };
  return { tone: 'info', text: `이 질문의 답 일부는 개인정보 보호를 위해 범위로 보이거나 비공개로 표시될 수 있습니다.` };
}

export type PreflightStatus = 'idle' | 'checking' | 'error' | 'done';

/** 입력칸 아래 한 줄 상태. */
export function preflightStatusLine(status: PreflightStatus, a: PreflightRiskAssessment | null): string {
  if (status === 'checking') return '보내기 전에 개인정보 보호 기준으로 확인하는 중';
  if (status === 'error') return '미리 확인하지 못했습니다. 보내면 서버가 확인합니다';
  if (a?.supported === false) return '보내면 서버가 개인정보 보호 기준으로 확인합니다';
  if (a?.understood === false) return '묻는 항목을 찾지 못했습니다. 처방, 시술, 진단, 시기처럼 물어보세요';
  if (a && !a.requiresWarning) return '확인했습니다. 그대로 답할 수 있는 질문입니다';
  return '보내면 서버가 개인정보 보호 기준으로 다시 확인합니다';
}

/** 답 아래 한 줄 설명. 바뀐 값이 없으면 null. */
export function protectionNote(p: ProtectionResult): Notice | null {
  const mode = p.releaseMode ?? '';
  if (mode === 'REFUSAL_EXTRACTION_FAILED') return { tone: 'info', text: '답을 확인하지 못해 보내지 않았습니다. 질문을 조금 바꿔 다시 물어보세요.' };
  if (mode.startsWith('REFUSAL')) return { tone: 'lock', text: '이 질문에는 개인정보 보호를 위해 답하지 않았습니다.' };
  if (mode === 'CASE_DROPPED') return { tone: 'lock', text: '환자를 알아볼 위험이 있는 사례는 이 답에서 뺐습니다.' };
  const sup = p.transformations.some((t) => t.action === 'suppress');
  const gen = p.transformations.some((t) => t.action === 'generalize' && !t.floor);
  const unit = p.transformations.some((t) => t.action === 'generalize' && t.floor);
  if (sup && gen) return { tone: 'lock', text: '개인을 알아볼 수 있는 값은 범위로 바꾸거나 비공개로 표시했습니다.' };
  if (sup) return { tone: 'lock', text: '개인을 알아볼 수 있는 값은 비공개로 표시했습니다.' };
  if (gen) return { tone: 'range', text: '개인을 알아볼 수 있는 값은 정확한 값 대신 범위로 표시했습니다.' };
  if (unit) return { tone: 'range', text: '나이 · 날짜는 정해진 공개 단위로 표시했습니다.' };
  return null;
}

/** '왜 그런가요?'를 눌렀을 때의 설명. */
export function whyText(p: ProtectionResult, caseLabel: string): string[] {
  const kept = p.transformations.filter((t) => !t.dropped);
  const sup = joinNames(kept.filter((t) => t.action === 'suppress').map(attrName));
  const gen = joinNames(kept.filter((t) => t.action === 'generalize' && !t.floor).map(attrName));
  const unit = joinNames(kept.filter((t) => t.action === 'generalize' && t.floor).map(attrName));
  const dropped = joinNames(p.transformations.filter((t) => t.dropped && t.caseRef).map((t) => refLabel(t.caseRef!)));
  const out: string[] = [];
  if ((p.releaseMode ?? '').startsWith('REFUSAL'))
    out.push('답을 고쳐도 개인을 알아볼 수 있는 내용이 남아, 답 대신 안내 문장을 보냈습니다.');
  if (dropped)
    out.push(`${josa(dropped, '은', '는')} 답을 고쳐도 다른 내용과 합치면 환자가 누구인지 알 수 있어, 그 사례 내용을 이 답에서 뺐습니다.`);
  if (sup)
    out.push(
      `${caseLabel} 환자의 ${josa(sup, '은', '는')} 그 값에 해당하는 환자가 아주 적어, 그대로 알려 드리면 그 환자가 누구인지 알 수 있게 됩니다. 그래서 이 값만 비공개로 하고 나머지는 그대로 답했습니다.`,
    );
  if (gen)
    out.push(`${josa(gen, '은', '는')} 정확한 값이면 해당하는 환자가 적어, 뜻은 유지하면서 한 단계 넓은 범위로 바꿔 보여 드렸습니다.`);
  if (unit)
    out.push(`${josa(unit, '은', '는')} 위험과 관계없이 정해진 공개 단위로만 보여 드립니다. 나이는 5세 구간, 날짜는 월 단위보다 자세히 보이지 않습니다.`);
  out.push('앞선 질문에서 나온 내용과 함께 판단하므로, 같은 값도 대화가 이어지면 다르게 보일 수 있습니다.');
  return out;
}

/** 세부 정보가 제한된 사례를 골랐을 때의 안내. */
export function restrictedNotice(caseLabel: string): string {
  return `${josa(caseLabel, '은', '는')} 지금까지 나온 내용만으로도 환자를 좁힐 수 있어, 새로 묻는 세부 값은 범위로 보이거나 비공개로 표시될 수 있습니다.`;
}

/** 세부 정보 요청 초안. 의료진이 사유를 이어 쓴다. */
export function requestDraft(caseLabel: string, names: string[]): string {
  const what = joinNames(names);
  return `${caseLabel} ${what ? `${what} ` : ''}세부 정보가 진료에 필요합니다. 사유: `;
}

/** 답을 진료 기록에 붙일 때 쓰는 평문. 넓힌 값에는 (범위)를 붙인다. */
export function answerPlainText(segments: { kind: string; text: string; transformationId?: string }[], tf: PrivacyTransformation[]): string {
  const byId = new Map(tf.map((t) => [t.id, t]));
  return segments
    .map((s) => {
      if (s.kind !== 'disclosure' || !s.transformationId) return s.text;
      const t = byId.get(s.transformationId);
      if (t?.action === 'suppress') return '(비공개)';
      if (t?.action === 'generalize') return `${s.text} (범위)`;
      return s.text;
    })
    .join('')
    .replace(/\*\*/g, '')
    .replace(/^\s{0,3}#{1,6}\s+/gm, '')
    .replace(/`/g, '');
}
