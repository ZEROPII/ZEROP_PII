import {
  CalendarDays,
  ChevronRight,
  CircleDot,
  ClipboardList,
  Hourglass,
  Lock,
  MapPin,
  Pill,
  Stethoscope,
  Syringe,
  UserRound,
  type LucideIcon,
} from 'lucide-react';
import { useEffect, useMemo } from 'react';
import { buildCaseNote, type NoteValue } from '../../lib/caseNote';
import { useTermDetect, useTerms } from '../../state/TermContext';
import { useSelectedCase, useWorkspace } from '../../state/WorkspaceContext';
import type { CaseId, ConversationSession, DisclosureHistoryEntry } from '../../types/domain';
import { EmptyState, LoadingState } from '../common/StatusViews';

const ATTR_ICON: Record<string, LucideIcon> = {
  DX: Stethoscope,
  COMORBID: Stethoscope,
  PROC: Syringe,
  MED: Pill,
  PLAN: ClipboardList,
  PERIOD: CalendarDays,
  DATE: CalendarDays,
  AGE: Hourglass,
  SEX: UserRound,
  REGION: MapPin,
  LOC: MapPin,
  STATE: MapPin,
};
/** 의료 용어 사전에서 찾아볼 수 있는 항목 (값을 누르면 용어 설명이 열린다) */
const TERM_ATTRS = new Set(['DX', 'MED', 'PROC', 'PLAN', 'COMORBID']);

function SectionTitle({ children, count }: { children: string; count?: number }) {
  return (
    <h3 className="mb-1.5 mt-5 flex items-baseline gap-1.5 text-[13px] font-bold text-ink first:mt-0">
      {children}
      {count != null && <span className="num text-xs font-medium text-ink-3">{count}</span>}
    </h3>
  );
}

function ValueText({ v, nodeId }: { v: NoteValue; nodeId: string | undefined }) {
  const { openTerm } = useTerms();
  if (v.action === 'suppress')
    return (
      <span className="lock-token" title="개인을 알아볼 수 있는 값이라 비공개로 처리했습니다">
        <Lock className="h-3 w-3" strokeWidth={2.2} aria-hidden />
        비공개
      </span>
    );
  const text = v.text ?? '';
  const body = nodeId ? (
    <button type="button" className="wikilink" onClick={() => openTerm(nodeId)} title="의료 용어 설명 보기">
      {text}
    </button>
  ) : (
    <span>{text}</span>
  );
  if (v.action === 'generalize')
    return (
      <span>
        <span className="range-value">{body}</span>
        <span className="range-tag">범위</span>
      </span>
    );
  return body;
}

/** 사례 노트: 속성 · 연결된 질문(백링크) · 같은 값이 나온 사례(링크된 언급) */
function NoteView({ onJump }: { onJump(caseId: CaseId, messageId: string): void }) {
  const { state, actions } = useWorkspace();
  const { caseId, summary, disclosures, session } = useSelectedCase();
  const cases = useMemo(() => state.cases.data ?? [], [state.cases.data]);

  // 같은 값 찾기에 다른 사례의 공개 이력도 쓴다 (아직 안 받았거나 다시 받아야 하면 받는다)
  useEffect(() => {
    for (const c of cases) {
      const slot = state.disclosures[c.caseId];
      if (!slot || slot.status === 'idle') actions.loadDisclosures(c.caseId);
    }
  }, [cases, state.disclosures, actions]);

  const allEntries = useMemo(
    () => Object.fromEntries(Object.entries(state.disclosures).map(([k, v]) => [k, v.data])) as Record<CaseId, DisclosureHistoryEntry[] | undefined>,
    [state.disclosures],
  );
  const sessions = useMemo(
    () => Object.fromEntries(Object.entries(state.sessions).map(([k, v]) => [k, v.data])) as Record<CaseId, ConversationSession | undefined>,
    [state.sessions],
  );
  const note = useMemo(
    () => (caseId && disclosures?.data ? buildCaseNote({ caseId, entries: disclosures.data, allEntries, sessions, cases }) : null),
    [caseId, disclosures?.data, allEntries, sessions, cases],
  );

  // 진단 · 약 · 시술 값은 용어 사전에서 찾아 누르면 설명이 열리게 한다
  const termValues = useMemo(
    () => (note ? note.properties.flatMap((p) => (TERM_ATTRS.has(p.attribute) ? p.values.map((v) => v.text ?? '') : [])) : []),
    [note],
  );
  const { mentions } = useTermDetect(termValues);

  if (!caseId || !summary) return <EmptyState message="사례를 고르면 지금까지 나온 내용이 노트로 정리됩니다." />;
  if (disclosures?.status === 'error') return <EmptyState message="노트를 만들 내용을 불러오지 못했습니다." />;
  if (!note) return <LoadingState compact label="노트를 정리하는 중" />;

  let ti = 0;
  const asked = session?.data?.questionCount ?? 0;
  return (
    <div className="px-4 pb-20 pt-4">
      <div className="flex items-baseline gap-2">
        <h3 className="text-lg font-bold tracking-[-0.02em] text-ink">{summary.label}</h3>
        <span className="min-w-0 truncate text-[13px] font-semibold text-ink-2" title={summary.diagnosis}>
          {summary.diagnosis}
        </span>
      </div>
      <p className="mt-0.5 text-xs text-ink-3">
        과거 환자 한 명의 기록 · 유사도 {summary.similarityRank}위{asked ? ` · 질문 ${asked}회` : ''}
      </p>

      <SectionTitle>지금까지 보인 내용</SectionTitle>
      {note.properties.length === 0 ? (
        <p className="text-[13px] text-ink-3">아직 답에 나온 내용이 없습니다.</p>
      ) : (
        <dl className="overflow-hidden rounded-control border border-line bg-surface">
          {note.properties.map((p) => {
            const Icon = ATTR_ICON[p.attribute] ?? CircleDot;
            const linkable = TERM_ATTRS.has(p.attribute);
            return (
              <div key={p.attribute} className="grid grid-cols-[16px_64px_minmax(0,1fr)] items-start gap-x-2.5 border-b border-line px-3 py-2.5 last:border-b-0">
                <Icon className="mt-[3px] h-3.5 w-3.5 text-ink-3" aria-hidden />
                <dt className="text-[13px] text-ink-3">{p.label}</dt>
                <dd className="min-w-0 space-y-1 break-words text-[13px] font-medium text-ink">
                  {p.values.map((v) => {
                    const m = linkable ? mentions[ti++] : undefined;
                    return (
                      <div key={`${v.action}:${v.text}`}>
                        <ValueText v={v} nodeId={m?.[0]?.node_id} />
                      </div>
                    );
                  })}
                </dd>
              </div>
            );
          })}
        </dl>
      )}
      <p className="mt-1.5 text-[11px] leading-4 text-ink-3">AI 답에 실제로 보인 값만 모읍니다. 범위 · 비공개 값은 답과 같은 모양입니다.</p>

      <SectionTitle count={note.backlinks.length}>질문별 기록</SectionTitle>
      <ol className="relative ml-1 border-l border-line">
        {note.backlinks.map((b) => {
          const elsewhere = b.askedIn && b.askedIn !== caseId;
          const content = (
            <>
              <span className="flex items-center gap-1.5 text-[11px] font-semibold text-iris-text">
                {b.turn === 0 ? '사례 검색' : b.questionNo != null ? `질문 ${b.questionNo}` : '질문'}
                {elsewhere && <span className="font-normal text-ink-3">{b.askedInLabel} 대화에서</span>}
              </span>
              <span className="mt-0.5 line-clamp-2 block text-[13px] leading-5 text-ink">{b.question}</span>
              <span className="mt-1 flex flex-wrap gap-1">
                {b.facts.map((f, i) => (
                  <span key={i} className="inline-flex max-w-full items-center gap-1 truncate rounded-[5px] bg-surface-2 px-1.5 py-px text-[11px] text-ink-2">
                    {f.label}
                    {f.action === 'suppress' ? <Lock className="h-2.5 w-2.5 text-emr-lock" aria-label="비공개" /> : <span className="truncate text-ink">{f.text}</span>}
                    {f.action === 'generalize' && <span className="text-iris-text">범위</span>}
                  </span>
                ))}
              </span>
            </>
          );
          return (
            <li key={b.turn} className="relative pl-4">
              <span aria-hidden className="absolute -left-[4.5px] top-[11px] h-2 w-2 rounded-full border-2 border-surface bg-iris" />
              {b.messageId && b.askedIn ? (
                <button
                  type="button"
                  onClick={() => onJump(b.askedIn!, b.messageId!)}
                  className="block w-full rounded-control px-2 py-1.5 text-left hover:bg-surface-2"
                  title="대화에서 이 질문으로 가기"
                >
                  {content}
                </button>
              ) : (
                <div className="px-2 py-1.5">{content}</div>
              )}
            </li>
          );
        })}
      </ol>

      {note.linked.length > 0 && (
        <details className="group mt-5 rounded-control border border-line bg-surface">
          <summary className="flex cursor-pointer list-none items-center gap-1.5 px-3 py-2.5 text-[13px] font-semibold text-ink [&::-webkit-details-marker]:hidden">
            <ChevronRight className="h-3.5 w-3.5 text-ink-3 transition-transform group-open:rotate-90" aria-hidden />
            다른 사례와 같은 값
            <span className="num text-xs font-medium text-ink-3">{note.linked.length}</span>
          </summary>
          <ul className="space-y-1.5 border-t border-line px-3 py-2.5 text-[13px]">
            {note.linked.map((l) => (
              <li key={`${l.label}:${l.value}`} className="leading-6">
                <span className="text-ink-3">{l.label}</span> <span className="font-medium text-ink">{l.value}</span>
                <span className="ml-1 inline-flex flex-wrap gap-x-1.5">
                  {l.cases.map((c) => (
                    <button key={c.caseId} type="button" className="wikilink text-[13px]" onClick={() => actions.selectCase(c.caseId)}>
                      {c.label}
                    </button>
                  ))}
                </span>
              </li>
            ))}
          </ul>
          <p className="px-3 pb-2.5 text-[11px] leading-4 text-ink-3">여러 사례에 같이 나온 값은 비슷한 환자 무리에 공통인 특징입니다.</p>
        </details>
      )}
    </div>
  );
}

/** 의료진 화면 오른쪽: 사례 노트 (보호 담당자 메시지는 오른쪽 아래 상담 창으로 옮겼다) */
export function CaseNotePanel({ onJump }: { onJump(caseId: CaseId, messageId: string): void }) {
  return (
    <section aria-labelledby="case-note-title" className="panel flex h-full min-h-0 flex-col overflow-hidden">
      <header className="flex h-11 shrink-0 items-center border-b border-line px-4">
        <h2 id="case-note-title" className="text-[13px] font-semibold text-ink">
          사례 노트
        </h2>
      </header>
      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto">
        <NoteView onJump={onJump} />
      </div>
    </section>
  );
}
