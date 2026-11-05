import { ChevronRight, Lock, MessageSquareText } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { EmptyState, ErrorState, LoadingState } from '../components/common/StatusViews';
import { formatTime } from '../lib/format';
import { useAuth } from '../state/AuthContext';
import { useClinicMessages } from '../state/ClinicMessages';
import { useWorkspace } from '../state/WorkspaceContext';
import type { ClinicHistoryItem } from '../types/domain';

function when(epochSec: number): string {
  return new Date(epochSec * 1000).toLocaleString('ko-KR', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
}

/** 이 계정의 대화 목록. 지난 대화는 읽기 전용 기록으로 남아 보안 담당자가 볼 수 있다. */
function PastConversations() {
  const { api, state } = useWorkspace();
  const [items, setItems] = useState<ClinicHistoryItem[] | null>(null);
  const version = state.patient.data?.contextId;
  useEffect(() => {
    if (!api.listHistory) return;
    const ctl = new AbortController();
    api.listHistory(ctl.signal).then(setItems, () => setItems([]));
    return () => ctl.abort();
  }, [api, version]);
  const past = (items ?? []).filter((x) => !x.current && x.questions > 0);
  if (!api.listHistory || !past.length) return null;
  return (
    <section className="panel overflow-hidden">
      <header className="flex items-baseline justify-between gap-3 border-b border-line px-4 py-3">
        <h2 className="text-[15px] font-bold text-ink">지난 진료</h2>
        <span className="text-xs text-ink-3">읽기 전용 기록</span>
      </header>
      <ul>
        {past.map((x) => (
          <li key={x.id} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 border-b border-line px-4 py-3 last:border-b-0">
            <span className="num w-[7.5em] shrink-0 text-xs text-ink-3">{when(x.startedAt)}</span>
            <span className="min-w-0 flex-1 text-[13px] text-ink">
              {x.patientId && (
                <span className="mr-2 font-mono font-semibold" title="진료한 환자의 EMR 환자 번호">
                  {x.patientId}
                </span>
              )}
              {x.patient}
              <span className="ml-2 text-ink-3">{x.purpose}</span>
            </span>
            <span className="text-xs text-ink-2">
              질문 {x.questions}회{x.archived ? ' · 보관된 기록' : ''}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** 조회 기록 (의료진): 이번 진료에서 사례별로 물은 질문. 재식별 위험 숫자는 보여 주지 않는다. */
export function HistoryPage() {
  const { state, actions } = useWorkspace();
  const navigate = useNavigate();
  const msgs = useClinicMessages();
  const product = useAuth().status === 'user';
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
        <PastConversations />
        <p className="px-1 text-xs leading-5 text-ink-3">
          질문과 답, 세부 정보 요청은 MediCloak 감사 기록에 남고 개인정보 보호 담당자가 확인할 수 있습니다.
          {product ? ' 기록은 병원 서버의 DB에 남습니다.' : ' 서버를 다시 켜면 데모 기록은 지워집니다.'}
        </p>
      </div>
    </div>
  );
}
