import { ArrowUpRight, Calculator, Gauge, MailQuestion, MessageSquare, Network, ScrollText } from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { apiMode } from '../api';
import { monitorApi } from '../api/monitorApi';
import { ChatMessage } from '../components/chat/ChatMessage';
import { Card, CardHeader } from '../components/common/Card';
import { StatusIcon } from '../components/common/StatusChip';
import { EmptyState, ErrorState, LoadingState } from '../components/common/StatusViews';
import { DisclosureHistoryPanel } from '../components/disclosure/DisclosureHistoryPanel';
import { ClueGraph } from '../components/graph/ClueGraph';
import { ProtectionBadge } from '../components/layout/ProtectionBadge';
import { RiskPanel } from '../components/risk/RiskPanel';
import { entryValue } from '../lib/caseNote';
import { ATTR_LABEL } from '../lib/clinicianCopy';
import type { ClueFact } from '../lib/clueGraph';
import { usePreflight } from '../state/usePreflight';
import { useSuggestions } from '../state/useSuggestions';
import { useSelectedCase, useWorkspace } from '../state/WorkspaceContext';
import type { CaseId } from '../types/domain';
import type { ThreadResult } from '../types/monitor';

const POLL_MS = 3000;

/** 데모 서버의 환자 맥락 id는 'ws-<대화 번호>:patient'다. 관제 상세로 바로 가는 데 쓴다. */
function monitorSessionOf(contextId: string | undefined): string | null {
  const m = contextId ? /^ws-(.+):patient$/.exec(contextId) : null;
  return m ? m[1] : null;
}

/** 이 질문이 오면 어떻게 답할지 미리 센다. 상태를 바꾸지 않고 대화에도 보내지 않는다. */
function WhatIfBox({ caseId, sessionId, label, version }: { caseId: CaseId; sessionId: string; label: string; version: number }) {
  const [q, setQ] = useState('');
  const pf = usePreflight(caseId, sessionId, q);
  const suggestions = useSuggestions(caseId, version);
  const a = pf.assessment && pf.assessment.caseId === caseId && pf.assessment.question === q.trim() ? pf.assessment : null;

  let result: ReactNode = <span className="text-ink-3">질문을 넣으면 그대로 답했을 때의 후보 수와 방어 규칙이 할 일을 셉니다.</span>;
  if (pf.status === 'checking') result = <span className="text-ink-3">후보 수를 세는 중</span>;
  else if (pf.status === 'error') result = <span className="text-danger-text">미리 세지 못했습니다.</span>;
  else if (a?.supported === false) result = <span className="text-ink-3">이 서버는 미리 세기를 지원하지 않습니다.</span>;
  else if (a?.understood === false) result = <span className="text-ink-3">묻는 항목을 찾지 못했습니다. 나이, 진단, 약, 시기처럼 물어보세요.</span>;
  else if (a?.requiresWarning)
    result = (
      <span className="inline-flex gap-1.5 text-caution-text">
        <StatusIcon tone="caution" className="mt-1 h-2.5 w-2.5 shrink-0" />
        <span>{a.message}</span>
      </span>
    );
  else if (a && a.projectedK != null)
    result = (
      <span className="inline-flex gap-1.5 text-safe-text">
        <StatusIcon tone="safe" className="mt-1 h-2.5 w-2.5 shrink-0" />
        그대로 답해도 후보 {a.projectedK.toLocaleString()}명입니다 (기준 통과).
      </span>
    );

  return (
    <div className="shrink-0 border-t border-line bg-surface px-4 py-3">
      <label htmlFor="whatif" className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold text-ink-2">
        <Calculator className="h-3.5 w-3.5" aria-hidden />
        질문 미리 세기
        <span className="font-normal text-ink-3">의료진 대화에는 보내지 않습니다</span>
      </label>
      <input
        id="whatif"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder={`${label}에 이런 질문이 오면? (예: 시술 받은 시기를 월 단위로)`}
        className="h-9 w-full rounded-control border border-line-input bg-surface px-3 text-[13px] text-ink outline-none placeholder:text-ink-3 focus:border-focus"
      />
      {suggestions.length > 0 && !q && (
        <div className="mt-1.5 flex gap-1.5 overflow-x-auto pb-0.5">
          {suggestions.slice(0, 6).map((s) => (
            <button
              key={s.question}
              type="button"
              onClick={() => setQ(s.question)}
              title={s.question}
              className="h-7 shrink-0 rounded-full border border-line px-2.5 text-xs text-ink-2 hover:border-line-input hover:text-ink"
            >
              {s.label}
            </button>
          ))}
        </div>
      )}
      <p className="mt-1.5 text-[13px] leading-5" aria-live="polite">
        {result}
      </p>
      {a?.requiresWarning && a.suggestions.length > 0 && (
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-ink-3">대신 물어볼 수 있는 질문</span>
          {a.suggestions.map((s) => (
            <button
              key={s.question}
              type="button"
              onClick={() => setQ(s.question)}
              title={s.question}
              className="h-7 rounded-full border border-caution px-2.5 text-xs font-semibold text-caution-text hover:bg-caution-tint"
            >
              {s.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** 의료진 화면 대화를 보안 담당자 쪽에서 본다: 답 속 보호 표시와 후보 수 변화(읽기 전용). */
function TranscriptPanel() {
  const { actions } = useWorkspace();
  const { caseId, summary, session, risk } = useSelectedCase();
  const data = session?.data;
  const scrollRef = useRef<HTMLDivElement>(null);
  const count = data?.messages.length ?? 0;
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight });
  }, [caseId, count]);

  return (
    <Card className="flex h-full min-h-0 flex-col overflow-hidden">
      <CardHeader
        title={
          <span className="inline-flex items-center gap-2">
            <MessageSquare className="h-4 w-4 text-ink-3" aria-hidden />
            {summary ? `${summary.label} 대화` : '대화'}
            <span className="text-xs font-normal text-ink-3">의료진 화면에 나간 그대로</span>
          </span>
        }
        aside={data ? `질문 ${data.questionCount}회` : undefined}
      />
      {risk && !risk.disclosureAllowed && (
        <p className="flex items-center gap-2 border-b border-line bg-caution-tint px-4 py-2 text-xs text-caution-text">
          <StatusIcon tone="caution" className="h-3 w-3 shrink-0" />
          {summary?.label} 후보가 {risk.k}명이라 새 단서는 넓히거나 가려서 답합니다. 의료진 화면에는 '세부 정보 제한'으로만 보입니다.
        </p>
      )}
      <div ref={scrollRef} className="scroll-thin min-h-0 flex-1 space-y-5 overflow-y-auto bg-page px-4 py-5">
        {!caseId ? (
          <EmptyState message="왼쪽에서 사례를 고르세요." />
        ) : !session || session.status === 'loading' || session.status === 'idle' ? (
          <LoadingState label="대화 기록을 불러오는 중" />
        ) : session.status === 'error' ? (
          <ErrorState message={session.error ?? '대화를 불러오지 못했습니다.'} onRetry={() => actions.loadSession(caseId, true)} />
        ) : data && data.messages.length === 0 ? (
          <EmptyState message="의료진이 아직 이 사례에 묻지 않았습니다. 의료진 화면에서 질문하면 여기에 바로 나타납니다." />
        ) : (
          data?.messages.map((m) => <ChatMessage key={m.messageId} message={m} />)
        )}
      </div>
      {caseId && data && <WhatIfBox caseId={caseId} sessionId={data.sessionId} label={summary?.label ?? '이 사례'} version={count} />}
    </Card>
  );
}

type SideTab = 'history' | 'graph';

/**
 * 보안 담당자 '의료진 대화' 화면: 의료진 화면에서 옮겨 온 위험 분석을 모두 모은다.
 *   왼쪽: 후보 렌즈와 사례별 후보 수 막대 / 가운데: 대화와 질문 미리 세기 / 오른쪽: 나간 정보 · 판정 근거, 단서 그래프
 * 의료진이 다른 탭에서 질문해도 3초마다 새로 받는다.
 */
export function WatchPage() {
  const { state, actions } = useWorkspace();
  const { summary } = useSelectedCase();
  const [tab, setTab] = useState<SideTab>('history');
  const [thread, setThread] = useState<ThreadResult | null>(null);
  const cases = useMemo(() => state.cases.data ?? [], [state.cases.data]);
  const sid = monitorSessionOf(state.patient.data?.contextId);
  const p = state.patient.data;

  useEffect(() => {
    const t = window.setInterval(() => void actions.refreshLive(), POLL_MS);
    return () => window.clearInterval(t);
  }, [actions]);

  // 단서 그래프에는 모든 사례의 공개 이력을 쓴다
  useEffect(() => {
    for (const c of cases) {
      const slot = state.disclosures[c.caseId];
      if (!slot || slot.status === 'idle') actions.loadDisclosures(c.caseId);
    }
  }, [cases, state.disclosures, actions]);

  // 의료진이 보낸 세부 정보 요청이 기다리고 있으면 위에 알린다
  useEffect(() => {
    if (!sid || apiMode !== 'http') return;
    let alive = true;
    const load = () => monitorApi.thread(sid).then((t) => alive && setThread(t), () => undefined);
    void load();
    const t = window.setInterval(load, POLL_MS);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, [sid]);

  const facts = useMemo<ClueFact[]>(
    () =>
      cases.flatMap((c) =>
        (state.disclosures[c.caseId]?.data ?? []).map((e) => ({
          caseRef: c.label.replace(/\s+/g, ''),
          caseLabel: c.label,
          attribute: e.attribute,
          attributeLabel: ATTR_LABEL[e.attribute] ?? e.attributeLabel,
          value: entryValue(e),
          action: e.action,
          turn: e.turn,
        })),
      ),
    [cases, state.disclosures],
  );
  const pending = thread?.row.pending_request ? thread.messages[thread.messages.length - 1] : null;

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1.5 px-4 pt-3 md:px-6">
        <p className="min-w-0 text-[13px] text-ink-2">
          의료진 화면 대화를 숫자와 함께 봅니다.
          {p && (
            <span className="ml-1.5 text-ink">
              질의 환자 <span className="font-mono">{p.trialId ?? '–'}</span>, {p.ageSexLabel}, {p.primaryDiagnosis}, {p.queryPurpose}
            </span>
          )}
        </p>
        <span className="ml-auto flex flex-wrap items-center gap-2">
          <ProtectionBadge policy={state.policy} />
          {sid && apiMode === 'http' && (
            <Link to={`/monitor?s=${encodeURIComponent(sid)}`} className="btn-ghost btn-sm">
              관제에서 이 대화 보기 <ArrowUpRight className="h-3.5 w-3.5" aria-hidden />
            </Link>
          )}
        </span>
      </div>
      {pending && (
        <div role="status" className="mx-4 mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-control border border-iris bg-iris-tint px-3 py-2 text-[13px] md:mx-6">
          <MailQuestion className="h-4 w-4 shrink-0 text-iris-text" aria-hidden />
          <span className="min-w-0 flex-1">
            <strong className="font-semibold">{pending.kind === 'access_request' ? '의료진 세부 정보 요청' : '의료진 답장'}</strong>
            {pending.case && <span className="ml-1 text-ink-2">{pending.case.replace(/^사례(\d+)$/, '사례 $1')}</span>}
            <span className="ml-2 text-ink-2">{pending.text}</span>
          </span>
          <Link to={`/monitor?s=${encodeURIComponent(sid ?? '')}`} className="btn-primary btn-sm">
            관제에서 답하기
          </Link>
        </div>
      )}
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 overflow-y-auto p-3 md:px-6 md:pb-6 lg:grid-cols-[288px_minmax(380px,1fr)_minmax(320px,380px)] lg:overflow-hidden">
        <aside aria-label="재식별 위험" className="scroll-thin lg:min-h-0 lg:overflow-y-auto">
          <RiskPanel />
        </aside>
        <section aria-label="의료진 대화" className="flex min-h-[520px] flex-col lg:min-h-0">
          <TranscriptPanel />
        </section>
        <aside aria-label="나간 정보와 단서 그래프" className="flex flex-col gap-3 lg:min-h-0">
          <div role="tablist" aria-label="오른쪽 영역" className="flex shrink-0 gap-1 rounded-control bg-surface-2 p-1">
            {(
              [
                ['history', '나간 정보와 판정 근거', ScrollText],
                ['graph', '단서 그래프', Network],
              ] as const
            ).map(([id, label, Icon]) => (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={tab === id}
                onClick={() => setTab(id)}
                className={`inline-flex h-8 flex-1 items-center justify-center gap-1.5 rounded-[8px] text-[13px] font-semibold ${
                  tab === id ? 'bg-surface text-ink shadow-sm' : 'text-ink-3 hover:text-ink'
                }`}
              >
                <Icon className="h-3.5 w-3.5" aria-hidden />
                {label}
              </button>
            ))}
          </div>
          {tab === 'history' ? (
            <div className="flex min-h-[360px] flex-1 flex-col lg:min-h-0">
              <DisclosureHistoryPanel />
            </div>
          ) : (
            <Card className="scroll-thin min-h-0 overflow-y-auto">
              <CardHeader
                title={
                  <span className="inline-flex items-center gap-2">
                    <Gauge className="h-4 w-4 text-ink-3" aria-hidden />
                    사례와 단서
                  </span>
                }
                aside={`사례 ${cases.length}건 전체`}
              />
              <ClueGraph
                facts={facts}
                focusCase={summary ? summary.label.replace(/\s+/g, '') : null}
                onPickCase={(ref) => {
                  const c = cases.find((x) => x.label.replace(/\s+/g, '') === ref);
                  if (c) actions.selectCase(c.caseId);
                }}
              />
            </Card>
          )}
        </aside>
      </div>
    </div>
  );
}
