import { ChevronRight, Lock, MessageSquareText } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { EmptyState, ErrorState, LoadingState } from '../components/common/StatusViews';
import { formatTime } from '../lib/format';
import { useClinicMessages } from '../state/ClinicMessages';
import { useWorkspace } from '../state/WorkspaceContext';

/** 조회 기록 (의료진): 이번 진료에서 사례별로 물은 질문. 재식별 위험 숫자는 보여 주지 않는다. */
export function HistoryPage() {
  const { state, actions } = useWorkspace();
  const navigate = useNavigate();
  const msgs = useClinicMessages();
  const { cases, sessions, riskStates } = state;
  const open = (caseId: string) => {
    actions.selectCase(caseId);
    navigate('/');
  };

  return (
    <div className="scroll-thin h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl space-y-3 p-4 md:p-6">
        <section className="panel overflow-hidden">
          <header className="flex items-baseline justify-between gap-3 border-b border-line px-4 py-3">
            <h2 className="text-[15px] font-bold text-ink">이번 진료의 조회 기록</h2>
            <span className="text-xs text-ink-3">사례를 누르면 그 대화로 갑니다</span>
          </header>
          {cases.status === 'error' ? (
            <ErrorState message={cases.error ?? '사례를 불러오지 못했습니다.'} onRetry={actions.reloadAll} />
          ) : !cases.data ? (
            <LoadingState />
          ) : cases.data.length === 0 ? (
            <EmptyState message="조회한 사례가 없습니다." />
          ) : (
            <ul>
              {cases.data.map((c) => {
                const session = sessions[c.caseId]?.data;
                const questions = (session?.messages ?? []).filter((m) => m.role === 'user' && m.status === 'sent');
                const last = questions[questions.length - 1];
                const restricted = riskStates.data?.[c.caseId] ? !riskStates.data[c.caseId].disclosureAllowed : false;
                const notes = msgs.messages.filter((m) => m.caseId === c.caseId).length;
                return (
                  <li key={c.caseId} className="border-b border-line last:border-b-0">
                    <button type="button" onClick={() => open(c.caseId)} className="flex w-full items-center gap-3 px-4 py-3.5 text-left hover:bg-surface-2">
                      <span className="min-w-0 flex-1">
                        <span className="flex flex-wrap items-baseline gap-x-2">
                          <span className="text-[15px] font-bold text-ink">{c.label}</span>
                          <span className="truncate text-[13px] text-ink-2">{c.diagnosis}</span>
                        </span>
                        <span className="mt-0.5 block truncate text-[13px] text-ink-2">
                          {!session
                            ? '이번 진료에서 아직 열지 않았습니다'
                            : questions.length === 0
                              ? '열었지만 아직 묻지 않았습니다'
                              : `질문 ${questions.length}회, 마지막 질문: ${last.segments.map((s) => s.text).join('')}`}
                        </span>
                        {(restricted || notes > 0 || last) && (
                          <span className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-ink-3">
                            {last && <span className="num">마지막 질문 {formatTime(last.createdAt)}</span>}
                            {restricted && (
                              <span className="inline-flex items-center gap-1 rounded-[5px] bg-emr-lock-tint px-1.5 py-px font-semibold text-emr-lock">
                                <Lock className="h-3 w-3" aria-hidden /> 세부 정보 제한
                              </span>
                            )}
                            {notes > 0 && (
                              <span className="inline-flex items-center gap-1 rounded-[5px] bg-surface-2 px-1.5 py-px text-ink-2">
                                <MessageSquareText className="h-3 w-3" aria-hidden /> 보호 담당자 메시지 {notes}
                              </span>
                            )}
                          </span>
                        )}
                      </span>
                      <ChevronRight className="h-4 w-4 shrink-0 text-ink-3" aria-hidden />
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
        <p className="px-1 text-xs leading-5 text-ink-3">
          질문과 답, 세부 정보 요청은 MediCloak 감사 기록에 남고 개인정보 보호 담당자가 확인할 수 있습니다. 서버를 다시 켜면 데모 기록은 지워집니다.
        </p>
      </div>
    </div>
  );
}
