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
  add_rule: '질문 패턴을 규칙에 추가',
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
  clinic_question: '의료진 질문',
};

const PURPOSE_KO: Record<string, string> = { PRESCRIPTION: '처방', TREATMENT_PROCEDURE: '시술·치료', COURSE_CARE: '경과·관리' };

/** 사유와 메모 칸: 질문 기록은 본문 대신 어느 사례에 무엇을 보호했는지만 */
function detailOf(a: AuditEntry): string | null {
  if (a.action === 'clinic_question') {
    const parts = [a.case ? caseLabel(a.case) : null, a.protected ? `보호 ${a.protected}건` : '보호한 값 없음', a.release ? `공개 방식 ${a.release}` : null];
    return parts.filter(Boolean).join(' · ');
  }
  if (a.action === 'emr_launch') return a.purpose ? `${PURPOSE_KO[a.purpose] ?? a.purpose} 참고` : null;
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
                        <span className="text-ink-3">{e.job ?? '–'}</span>
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
