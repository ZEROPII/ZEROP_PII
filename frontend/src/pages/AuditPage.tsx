import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { MONITOR_UNAVAILABLE, monitorApi } from '../api/monitorApi';
import { Card, CardHeader } from '../components/common/Card';
import { EmptyState, ErrorState, LoadingState } from '../components/common/StatusViews';
import { useBackendInfo } from '../hooks/useBackendInfo';
import { ACTION_KO, detailOf, subjectsOf } from '../lib/auditText';
import { caseLabel, clockTime } from '../lib/time';
import type { AuditEntry } from '../types/monitor';

/** 감사 기록: 누가 언제 무엇을 했는지. 원문 열람은 사유와 함께 남는다. */
export function AuditPage() {
  const backend = useBackendInfo();
  // 서버 종류를 알기 전에는 아무것도 적지 않는다 (운영 서버에서 '데모 기록'이 잠깐 보이던 일)
  const aside = !backend
    ? undefined
    : backend.kind === 'medicloak'
      ? 'DB에 모두 남고, 여기에는 최근 2,000건을 보입니다'
      : '서버를 다시 켜면 지워지는 데모 기록입니다 (최근 2,000건)';
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
        <CardHeader title="감사 기록" aside={aside} />
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
                {items.map((e) => {
                  const who = subjectsOf(e);
                  return (
                  <tr key={e.id}>
                    <td className="num border-b border-line px-4 py-3 text-ink-2">{clockTime(e.at)}</td>
                    <td className="border-b border-line px-4 py-3">{e.actor}</td>
                    <td className="border-b border-line px-4 py-3 font-semibold">
                      {ACTION_KO[e.action] ?? e.action}
                      {e.high_risk && (
                        <span className="ml-1.5 whitespace-nowrap rounded-[4px] bg-danger-tint px-1 py-px text-[10.5px] font-semibold text-danger-text">고위험</span>
                      )}
                    </td>
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
                      {who && <span className="mt-0.5 block text-[11.5px] text-ink-3">{who}</span>}
                    </td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
