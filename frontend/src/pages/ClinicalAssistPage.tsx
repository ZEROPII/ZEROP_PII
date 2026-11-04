import { List, MessageSquare, NotebookText } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { CaseNotePanel, type NoteTab } from '../components/clinic/CaseNotePanel';
import { ClinicalChat, type JumpTarget } from '../components/clinic/ClinicalChat';
import { EmrCaseList } from '../components/clinic/EmrCaseList';
import { useClinicMessages } from '../state/ClinicMessages';
import { useSelectedCase, useWorkspace } from '../state/WorkspaceContext';
import type { CaseId } from '../types/domain';

type PanelTab = 'cases' | 'chat' | 'note';

const TABS: { id: PanelTab; label: string; icon: typeof List }[] = [
  { id: 'cases', label: '사례', icon: List },
  { id: 'chat', label: '대화', icon: MessageSquare },
  { id: 'note', label: '노트', icon: NotebookText },
];

/**
 * 의료진 화면 (병원 EMR 안의 진료 지원 AI): 비슷한 사례 | 묻고 답 받기 | 사례 노트 · 보호 담당자 메시지.
 * 재식별 위험 숫자는 이 화면 어디에도 없다. 같은 대화를 보안 담당자는 '의료진 대화' 화면에서 숫자와 함께 본다.
 * 넓은 화면은 3단, 좁은 화면(lg 미만)은 탭으로 한 영역씩 보여 준다.
 */
export function ClinicalAssistPage() {
  const [tab, setTab] = useState<PanelTab>('chat');
  const [noteTab, setNoteTab] = useState<NoteTab>('note');
  const [jump, setJump] = useState<JumpTarget | null>(null);
  const [focusNonce, setFocusNonce] = useState(0);
  const { actions } = useWorkspace();
  const { summary } = useSelectedCase();
  const msgs = useClinicMessages();

  const openMessages = useCallback(() => {
    setNoteTab('messages');
    setTab('note');
    setFocusNonce((n) => n + 1);
  }, []);

  // 머리줄 알림을 누르면(조회 기록 · 보호 안내에서 눌러 이 화면으로 와도) 메시지 탭을 연다
  const { openPending, consumeOpen } = msgs;
  useEffect(() => {
    if (!openPending) return;
    consumeOpen();
    openMessages();
  }, [openPending, consumeOpen, openMessages]);

  const onJump = useCallback(
    (caseId: CaseId, messageId: string) => {
      actions.selectCase(caseId);
      setJump({ caseId, messageId, nonce: Date.now() });
      setTab('chat');
    },
    [actions],
  );
  const onJumpDone = useCallback(() => setJump(null), []);
  const panelClass = (id: PanelTab) => `${tab === id ? 'flex' : 'hidden'} lg:flex min-h-0 flex-col`;

  return (
    <div className="flex h-full flex-col">
      <div role="tablist" aria-label="화면 영역" className="flex shrink-0 gap-1 border-b border-line bg-surface px-2 lg:hidden">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            role="tab"
            type="button"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
            className={`flex flex-1 items-center justify-center gap-1.5 border-b-2 py-2.5 text-[13px] font-semibold ${
              tab === id ? 'border-iris text-iris-text' : 'border-transparent text-ink-3'
            }`}
          >
            <Icon className="h-4 w-4" aria-hidden />
            {label}
            {id === 'chat' && summary && <span className="hidden font-normal text-ink-3 sm:inline">{summary.label}</span>}
            {id === 'note' && msgs.unread > 0 && (
              <span className="num grid h-4 min-w-4 place-items-center rounded-full bg-iris px-1 text-[10px] font-bold text-iris-on">{msgs.unread}</span>
            )}
          </button>
        ))}
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 p-3 md:p-4 lg:grid-cols-[264px_minmax(0,1fr)_336px]">
        <aside id="panel-cases" aria-label="비슷한 사례" className={panelClass('cases')}>
          <EmrCaseList onSelected={() => setTab('chat')} />
        </aside>
        <div id="panel-chat" className={panelClass('chat')}>
          <ClinicalChat jump={jump} onJumpDone={onJumpDone} onOpenMessages={openMessages} />
        </div>
        <aside id="panel-note" className={panelClass('note')}>
          <CaseNotePanel tab={noteTab} onTab={setNoteTab} onJump={onJump} focusNonce={focusNonce} />
        </aside>
      </div>
    </div>
  );
}
