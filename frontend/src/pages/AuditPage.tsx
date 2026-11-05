import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { MONITOR_UNAVAILABLE, monitorApi } from '../api/monitorApi';
import { Card, CardHeader } from '../components/common/Card';
import { EmptyState, ErrorState, LoadingState } from '../components/common/StatusViews';
import { useBackendInfo } from '../hooks/useBackendInfo';
import { caseLabel, clockTime } from '../lib/time';
import type { AuditEntry } from '../types/monitor';

const ACTION_KO: Record<string, string> = {
  reveal: '원문 열람',
  reviewed: '검토 완료',
  ask_clinician: '의료진에게 확인 요청',
  add_rule: '규칙 걸기',
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
};
const ATTR_KO: Record<string, string> = { AGE: '나이', SEX: '성별', REGION: '거주 지역', PERIOD: '시기', DX: '진단', PROC: '시술', MED: '처방 약', PLAN: '관리 계획' };

/** 사유와 메모 칸: 질문 기록은 본문 대신 어느 사례에 무엇을 보호했는지만 */
function detailOf(a: AuditEntry): string | null {
  if (a.action === 'clinic_question') {
    const parts = [a.case ? caseLabel(a.case) : null, a.protected ? `보호 ${a.protected}건` : '보호한 값 없음', a.release ? `내보낸 답 ${RELEASE_KO[a.release] ?? a.release}` : null];
    return parts.filter(Boolean).join(' · ');
  }
  if (a.action === 'add_rule' || a.action === 'remove_rule') {
    const what = `${a.case ? caseLabel(a.case) : ''} ${ATTR_KO[a.attribute ?? ''] ?? a.attribute ?? ''}`.trim();
    return [what, a.note].filter(Boolean).join(' · ') || null;
  }
  if (a.action === 'approve_release') {
    const items = (a.items ?? []).map((x) => `${caseLabel(x.case)} ${ATTR_KO[x.attribute] ?? x.attribute}`).join(', ');
    return [items, a.reason ? `사유: ${a.reason}` : null].filter(Boolean).join(' · ');
  }
  if (a.action === 'redteam_start')
    return [a.job, a.trigger === 'change' ? '설정이 바뀌어 자동' : a.trigger === 'daily' ? '정기 자동' : null, a.llm === 'live' ? '실제 LLM' : '결정적 응답기', a.per_type ? `유형마다 ${a.per_type}명` : '전체']
      .filter(Boolean)
      .join(' · ');
  if (a.action === 'redteam_compare')
    return [a.job, a.baseline ? `직전 ${a.baseline}` : null, LEVEL_KO[a.level ?? ''] ?? null, a.note].filter(Boolean).join(' · ');
  if (a.action === 'emr_launch' || a.action === 'emr_prefetch') {
    const parts = [a.purpose ? `${PURPOSE_KO[a.purpose] ?? a.purpose} 참고` : null, a.visit_dx ? `오늘 진단 ${a.visit_dx}${a.visit_date ? ` (${a.visit_date})` : ''}` : null,
      a.action === 'emr_prefetch'
        ? a.calls
          ? `환자 요약 · 검색된 사례를 대상 AI에 보냄 (호출 ${a.calls}번${a.ok === false ? ', 실패' : ''})`
          : `받아 둔 첫 답을 씀 (대상 AI 호출 없음${a.ok === false ? ', 실패' : ''})`
        : null];
    return parts.filter(Boolean).join(' · ') || null;
  }
  if (a.action === 'assist_draft') {
    const c = a.counts ?? {};
    const parts = [a.case ? caseLabel(a.case) : null, VERDICT_KO[a.verdict ?? ''] ?? null, c.release ? `공개 가능 ${c.release}` : null,
      c.consider ? `사유 확인 ${c.consider}` : null, a.writer === 'llm' ? 'AI 초안' : '정해진 문장'];
    return parts.filter(Boolean).join(' · ');
  }
  if (a.action.startsWith('login') || a.action === 'logout') return a.client ? `접속 주소 ${a.client}` : null;
  return null;
}

/** 감사 기록: 누가 언제 무엇을 했는지. 원문 열람은 사유와 함께 남는다. */
export function AuditPage() {
  const backend = useBackendInfo();
  const [items, setItems] = useState<AuditEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () =>
      monitorApi.audit().then(
        (x) => alive && (setItems(x), setError(null)),
        (e) => alive && setError(e instanceof Error ? e.message : MONITOR_UNAVAILABLE),
      );
    void load();
    const t = setInterval(load, 4000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  return (
    <div className="scroll-thin mx-auto h-full max-w-4xl overflow-y-auto p-4 md:p-6">
      <Card>
        <CardHeader title="감사 기록" aside={backend?.kind === 'medicloak' ? 'DB에 남는 기록 (최근 2,000건)' : '서버를 다시 켜면 지워지는 데모 기록입니다'} />
        {error ? (
          <ErrorState message={error} />
        ) : !items ? (
          <LoadingState />
        ) : items.length === 0 ? (
          <EmptyState message="아직 남은 기록이 없습니다. 원문 열람, 검토 표시, 의료진과 주고받은 메시지가 여기에 남습니다." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-[13px]">
              <thead>
                <tr className="text-left text-xs text-ink-3">
                  <th className="border-b border-line px-4 py-2.5 font-semibold">시각</th>
                  <th className="border-b border-line px-4 py-2.5 font-semibold">누가</th>
                  <th className="border-b border-line px-4 py-2.5 font-semibold">무엇을</th>
                  <th className="border-b border-line px-4 py-2.5 font-semibold">대화</th>
                  <th className="border-b border-line px-4 py-2.5 font-semibold">사유와 메모</th>
                </tr>
              </thead>
              <tbody>
                {items.map((e) => (
                  <tr key={e.id}>
                    <td className="num border-b border-line px-4 py-3 text-ink-2">{clockTime(e.at)}</td>
                    <td className="border-b border-line px-4 py-3">{e.actor}</td>
                    <td className="border-b border-line px-4 py-3 font-semibold">{ACTION_KO[e.action] ?? e.action}</td>
                    <td className="border-b border-line px-4 py-3">
                      {e.session ? (
                        <Link to={`/monitor?s=${encodeURIComponent(e.session)}`} className="font-mono text-iris-text hover:underline">
                          {e.trial}
                        </Link>
                      ) : (
                        // 대화가 없는 기록: 레드팀 실행 번호, 또는 열기 전 미리 준비한 질의 환자(trial)
                        <span className="font-mono text-ink-3">{e.job ?? e.trial ?? '–'}</span>
                      )}
                    </td>
                    <td className="border-b border-line px-4 py-3 text-ink-2">
                      {detailOf(e) ?? (
                        <>
                          {e.case && <span className="mr-1.5 font-semibold text-ink">{caseLabel(e.case)}</span>}
                          {e.reason ?? e.note ?? ''}
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
