import { useEffect, useState } from 'react';
import { monitorApi } from '../../api/monitorApi';
import { useWorkspace } from '../../state/WorkspaceContext';
import type { Narrowing } from '../../types/monitor';
import { Card, CardHeader } from '../common/Card';
import { EmptyState, ErrorState, LoadingState } from '../common/StatusViews';
import { NarrowingLadder, RangeMini } from '../viz/Instruments';

/**
 * 보안 담당자 '의료진 대화' 왼쪽: 고른 사례의 후보가 줄어든 과정(단서별)과 사례별 지금 후보 수.
 * 숫자는 /api/watch/{대화} 계약(의료진 화면과 같은 대화, 숫자 그대로)과 /narrowing에서 온다.
 */
export function WatchRiskPanel({ sid }: { sid: string | null }) {
  const { state, actions } = useWorkspace();
  const { riskStates, cases, policy, selectedCaseId, sessions } = state;
  const g = policy.data?.minK ?? 5;
  const s = policy.data?.suppressK ?? 3;
  const max = policy.data?.populationSize ?? 461;
  const risk = selectedCaseId ? riskStates.data?.[selectedCaseId] : undefined;
  const msgCount = selectedCaseId ? (sessions[selectedCaseId]?.data?.messages.length ?? 0) : 0;
  const [nar, setNar] = useState<{ key: string; data: Narrowing | null; error: string | null } | null>(null);
  const key = `${sid}|${selectedCaseId}|${risk?.version ?? ''}|${risk?.k ?? ''}|${msgCount}`;

  useEffect(() => {
    if (!sid || !selectedCaseId) return;
    const ctl = new AbortController();
    monitorApi.narrowing(sid, selectedCaseId, ctl.signal).then(
      (data) => setNar({ key, data, error: null }),
      (e) => {
        if (!(e instanceof DOMException)) setNar({ key, data: null, error: e instanceof Error ? e.message : '불러오지 못했습니다.' });
      },
    );
    return () => ctl.abort();
  }, [key, sid, selectedCaseId]);

  const label = cases.data?.find((c) => c.caseId === selectedCaseId)?.label ?? '사례';
  const k = risk?.k ?? null;

  return (
    <Card>
      <CardHeader title="재식별 위험" aside={<span className="num text-xs text-ink-3">기준 집단 {max.toLocaleString()}명</span>} />
      {riskStates.status === 'error' ? (
        <ErrorState message={riskStates.error ?? '후보 수를 불러오지 못했습니다.'} onRetry={actions.reloadAll} />
      ) : !riskStates.data || !cases.data ? (
        <LoadingState compact />
      ) : cases.data.length === 0 ? (
        <EmptyState message="표시할 사례가 없습니다." />
      ) : (
        <>
          <section aria-label={`${label} 후보가 줄어든 과정`} className="border-b border-line px-4 pb-3 pt-3.5">
            <p className="text-[13px] text-ink-2">
              {label}과 조건이 같은 과거 환자{' '}
              <b className={`num text-[22px] font-extrabold tracking-[-0.02em] ${k != null && k <= g ? 'text-danger-text' : 'text-ink'}`}>
                {k != null ? k.toLocaleString() : '–'}
              </b>
              명
            </p>
            {k != null && (
              <p className="num mt-0.5 text-xs text-ink-3">
                {k > g ? `넓힘 기준 ${g}명보다 ${k - g}명 많음` : k > s ? `넓힘 기준 ${g}명 이하: 새 단서는 넓히거나 가림` : `가림 기준 ${s}명 이하: 새 단서는 가림`}
              </p>
            )}
            <div className="mt-2.5">
              {!nar || nar.key !== key ? (
                <LoadingState compact />
              ) : nar.error || !nar.data ? (
                <p className="text-xs text-ink-3">{nar.error ?? '후보가 줄어든 과정을 불러오지 못했습니다.'}</p>
              ) : (
                <NarrowingLadder data={nar.data} />
              )}
            </div>
          </section>
          <section aria-label="사례별 후보 수" className="px-2 py-2">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-[11px] text-ink-3">
                  <th className="px-2 py-1 font-semibold">사례</th>
                  <th className="px-1 py-1 text-right font-semibold">유사도</th>
                  <th className="px-1 py-1 text-right font-semibold">후보</th>
                  <th className="px-2 py-1 font-semibold">
                    <span className="sr-only">로그 눈금</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {cases.data.map((c) => {
                  const r = riskStates.data?.[c.caseId];
                  const sel = c.caseId === selectedCaseId;
                  return (
                    <tr
                      key={c.caseId}
                      onClick={() => actions.selectCase(c.caseId)}
                      aria-selected={sel}
                      className={`cursor-pointer ${sel ? 'bg-iris-tint' : 'hover:bg-surface-2'}`}
                    >
                      <td className="rounded-l-cell px-2 py-1.5">
                        <button type="button" onClick={() => actions.selectCase(c.caseId)} className={`font-bold ${sel ? 'text-iris-text' : 'text-ink'}`}>
                          {c.label}
                        </button>
                      </td>
                      <td className="num px-1 py-1.5 text-right text-ink-3">{c.similarity != null ? c.similarity.toFixed(2) : '–'}</td>
                      <td className={`num px-1 py-1.5 text-right font-semibold ${r?.k != null && r.k <= g ? 'text-danger-text' : 'text-ink'}`}>
                        {r?.k != null ? r.k.toLocaleString() : '–'}
                      </td>
                      <td className="rounded-r-cell px-2 py-1.5">{r?.k != null && <RangeMini raw={null} now={r.k} max={max} g={g} width={72} />}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>
        </>
      )}
    </Card>
  );
}
