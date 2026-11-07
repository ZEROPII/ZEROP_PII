// 감사 기록 화면의 글 (AuditPage). 무엇을 했는지 · 사유와 메모 · 다룬 환자 기호.
// 환자 번호는 감사 기록에 없다: 같은 번호는 늘 같은 기호('P-3f9a1c')로 남아, 번호 없이 서로 맞춰 볼 수 있다 (ADR-0030).

import type { AuditEntry } from '../types/monitor';
import { caseLabel } from './time';

export const ACTION_KO: Record<string, string> = {
  reveal: '원문 열람',
  reviewed: '검토 완료',
  ask_clinician: '의료진에게 확인 요청',
  add_rule: '규칙 걸기',
  add_rule_failed: '규칙 걸기 실패',
  remove_rule: '규칙 풀기',
  approve_release: '가린 값 공개 승인',
  redteam_cancel: '레드팀 점검 멈춤',
  clinic_start: '의료진 새 대화 시작',
  redteam_start: '레드팀 점검 시작',
  access_request: '의료진 세부 정보 요청',
  clinician_reply: '의료진 답장',
  security_reply: '보안 담당자 답장',
  login: '로그인',
  logout: '로그아웃',
  login_failed: '로그인 실패',
  login_blocked: '로그인 잠시 막음',
  emr_launch: 'EMR에서 진료 지원 AI 열기',
  emr_prefetch: '첫 답 미리 준비 (열기 전)',
  clinic_question: '의료진 질문',
  assist_draft: '검토 보조 초안',
  redteam_compare: '레드팀 직전 점검과 비교',
  watch_preflight: '보안 담당자 질문 미리 세기',
  preflight_limited: '보내기 전 확인 한도 넘음',
};

const PURPOSE_KO: Record<string, string> = { PRESCRIPTION: '처방', TREATMENT_PROCEDURE: '시술·치료', COURSE_CARE: '경과·관리' };
const LEVEL_KO: Record<string, string> = { warn: '경고', caution: '주의', ok: '이상 없음', none: '첫 기준 점검' };
const VERDICT_KO: Record<string, string> = { release: '공개 권장', partial: '일부 공개 권장', consider: '사유 확인 뒤 결정', keep: '지금 처리 유지 권장', none: '공개할 값 없음' };
const RELEASE_KO: Record<string, string> = {
  RAW: '그대로',
  ROUNDED: '공개 단위로 바꾼 답',
  REWRITTEN: '고쳐 쓴 답',
  REWRITTEN_FALLBACK: '값만 바꾼 답',
  CASE_DROPPED: '사례를 뺀 답',
  REFUSAL: '거절 문장',
  REFUSAL_EXTRACTION_FAILED: '거절 문장 (추출 실패)',
  REFUSAL_TIMEOUT: '거절 문장 (시간 초과)',
};
const ATTR_KO: Record<string, string> = { AGE: '나이', SEX: '성별', REGION: '거주 지역', PERIOD: '시기', DX: '진단', PROC: '시술', MED: '처방 약', PLAN: '관리 계획' };

function join(parts: (string | null | undefined | false)[]): string | null {
  return parts.filter(Boolean).join(' · ') || null;
}

/** 사유와 메모 칸: 질문 기록은 본문 대신 어느 사례에 무엇을 보호했는지만 */
export function detailOf(a: AuditEntry): string | null {
  if (a.action === 'clinic_question')
    return join([a.case ? caseLabel(a.case) : null, a.protected ? `보호 ${a.protected}건` : '보호한 값 없음', a.release ? `내보낸 답 ${RELEASE_KO[a.release] ?? a.release}` : null]);
  if (a.action === 'reveal') return join([a.reason ? `사유: ${a.reason}` : null, a.note]);
  if (a.action === 'add_rule' || a.action === 'remove_rule' || a.action === 'add_rule_failed') {
    const what = `${a.case ? caseLabel(a.case) : ''} ${ATTR_KO[a.attribute ?? ''] ?? a.attribute ?? ''}`.trim();
    return join([what, a.note, a.action === 'add_rule_failed' && a.why ? `걸지 못한 까닭: ${a.why}` : null]);
  }
  if (a.action === 'approve_release') {
    const items = (a.items ?? []).map((x) => `${caseLabel(x.case)} ${ATTR_KO[x.attribute] ?? x.attribute}`).join(', ');
    // 고위험 승인(기준 아래로 내려가는 공개)은 화면이 '고위험' 표시를 따로 붙인다
    const kept = (a.kept ?? []).map((x) => `${caseLabel(x.case)} ${ATTR_KO[x.attribute] ?? x.attribute}`).join(', ');
    return join([items, kept ? `공개하지 않음: ${kept}` : null, a.k_min != null ? `공개 뒤 후보 ${a.k_min}명${a.high_risk ? ' (기준 아래)' : ''}` : null,
      a.reason ? `사유: ${a.reason}` : null]);
  }
  if (a.action === 'redteam_start')
    return join([a.job, a.trigger === 'change' ? '설정이 바뀌어 자동' : a.trigger === 'daily' ? '정기 자동' : null, a.llm === 'live' ? '실제 LLM' : '결정적 응답기', a.per_type ? `유형마다 ${a.per_type}명` : '전체']);
  if (a.action === 'watch_preflight') return join([a.case ? caseLabel(a.case) : null, a.question_chars != null ? `질문 ${a.question_chars}자` : null]);
  if (a.action === 'preflight_limited') return join([a.case ? caseLabel(a.case) : null, '짧은 시간에 미리 확인을 많이 써서 판정 없이 돌려줌']);
  if (a.action === 'redteam_compare') return join([a.job, a.baseline ? `직전 ${a.baseline}` : null, LEVEL_KO[a.level ?? ''] ?? null, a.note]);
  if (a.action === 'emr_launch' || a.action === 'emr_prefetch')
    return join([
      a.purpose ? `${PURPOSE_KO[a.purpose] ?? a.purpose} 참고` : null,
      a.visit_dx ? `오늘 진단 ${a.visit_dx}${a.visit_date ? ` (${a.visit_date})` : ''}` : null,
      a.action === 'emr_prefetch'
        ? a.calls
          ? `환자 요약 · 검색된 사례를 대상 AI에 보냄 (호출 ${a.calls}번${a.ok === false ? ', 실패' : ''})`
          : `받아 둔 첫 답을 씀 (대상 AI 호출 없음${a.ok === false ? ', 실패' : ''})`
        : null,
    ]);
  if (a.action === 'assist_draft') {
    const c = a.counts ?? {};
    return join([a.case ? caseLabel(a.case) : null, VERDICT_KO[a.verdict ?? ''] ?? null, c.release ? `공개 가능 ${c.release}` : null,
      c.consider ? `사유 확인 ${c.consider}` : null, a.writer === 'llm' ? 'AI 초안' : '정해진 문장']);
  }
  if (a.action.startsWith('login') || a.action === 'logout') return a.client ? `접속 주소 ${a.client}` : null;
  return null;
}

/** 다룬 환자: 지금 환자 기호와 사례(과거 환자)마다 기호. 기호가 없는 기록(로그인 등)은 null */
export function subjectsOf(a: AuditEntry): string | null {
  const past = (a.subjects ?? []).filter((x) => x.tag).map((x) => `${caseLabel(x.case)} ${x.tag}`);
  return join([a.patient_tag ? `지금 환자 ${a.patient_tag}` : null, past.length ? `과거 환자 ${past.join(', ')}` : null]);
}
