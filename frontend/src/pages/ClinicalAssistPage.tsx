import { ClipboardList, List, MessageSquare, NotebookText, PanelRightOpen } from 'lucide-react';
import { useCallback, useState } from 'react';
import { NavLink } from 'react-router-dom';
import { CaseNotePanel } from '../components/clinic/CaseNotePanel';
import { ClinicalChat, type JumpTarget } from '../components/clinic/ClinicalChat';
import { EmrCaseList } from '../components/clinic/EmrCaseList';
import { useClinicMessages } from '../state/ClinicMessages';
import { useSelectedCase, useWorkspace } from '../state/WorkspaceContext';
import type { CaseId } from '../types/domain';

type PanelTab = 'cases' | 'chat' | 'note';

const NOTE_KEY = 'medicloak.clinic.noteOpen';

/** 넓은 화면에서 사례 노트를 펼쳐 둘지 (이 브라우저에만 기억. 저장소를 못 쓰면 기본값 접힘) */
function readNoteOpen(): boolean {
  try {
    return window.localStorage.getItem(NOTE_KEY) === '1';
  } catch {
    return false;
  }
}

function writeNoteOpen(open: boolean): void {
  try {
    window.localStorage.setItem(NOTE_KEY, open ? '1' : '0');
  } catch {
    /* 저장하지 못해도 화면은 그대로 쓴다 */
  }
}

const TABS: { id: PanelTab; label: string; icon: typeof List }[] = [
  { id: 'cases', label: '사례', icon: List },
  { id: 'chat', label: '대화', icon: MessageSquare },
  { id: 'note', label: '노트', icon: NotebookText },
];

/**
 * 의료진 화면 (병원 EMR 안의 진료 지원 AI): 비슷한 사례 | 묻고 답 받기 | 사례 노트. 보호 담당자 메시지는 오른쪽 아래 상담 창(ProtectionDesk).
 * 재식별 위험 숫자는 이 화면 어디에도 없다. 같은 대화를 보안 담당자는 '의료진 대화' 화면에서 숫자와 함께 본다.
 * 넓은 화면은 사례 목록 | 대화 두 단이 기본이고, 사례 노트는 오른쪽 가는 띠를 눌러 펼친다 (진료 중에는 볼 거리를 줄인다).
 * 좁은 화면(lg 미만)은 탭으로 한 영역씩 보여 준다.
 */
export function ClinicalAssistPage() {
  const [tab, setTab] = useState<PanelTab>('chat');
  const [noteOpen, setNoteOpenState] = useState<boolean>(readNoteOpen);
  const setNoteOpen = useCallback((open: boolean) => {
    setNoteOpenState(open);
    writeNoteOpen(open);
  }, []);
  const [jump, setJump] = useState<JumpTarget | null>(null);
  const { state, actions } = useWorkspace();
  const { summary } = useSelectedCase();
  const msgs = useClinicMessages();

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

  if (state.noConversation) return <NoPatientOpen />;

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
          </button>
        ))}
      </div>
      <div
        className={`grid min-h-0 flex-1 grid-cols-1 gap-3 p-3 md:p-4 ${noteOpen ? 'lg:grid-cols-[264px_minmax(0,1fr)_336px]' : 'lg:grid-cols-[264px_minmax(0,1fr)_40px]'}`}
      >
        <aside id="panel-cases" aria-label="비슷한 사례" className={panelClass('cases')}>
          <EmrCaseList onSelected={() => setTab('chat')} />
        </aside>
        <div id="panel-chat" className={panelClass('chat')}>
          <ClinicalChat jump={jump} onJumpDone={onJumpDone} onOpenMessages={() => msgs.requestOpen()} />
        </div>
        <aside id="panel-note" className={`${panelClass('note')} ${noteOpen ? '' : 'lg:hidden'}`}>
          <CaseNotePanel onJump={onJump} onCollapse={() => setNoteOpen(false)} />
        </aside>
        {!noteOpen && (
          <button
            type="button"
            onClick={() => setNoteOpen(true)}
            className="panel hidden min-h-0 flex-col items-center gap-2 py-3 text-ink-2 hover:text-ink lg:flex"
            aria-label="사례 노트 펼치기"
            title="사례 노트 펼치기: 이 사례에서 지금까지 답에 나온 내용"
          >
            <PanelRightOpen className="h-4 w-4" aria-hidden />
            <span className="text-xs font-semibold [writing-mode:vertical-rl]">사례 노트</span>
          </button>
        )}
      </div>
    </div>
  );
}

/** 운영 모드에서 아직 EMR에서 환자를 열지 않았을 때 (진료 지원 AI는 환자를 열어야 시작한다). */
function NoPatientOpen() {
  return (
    <div className="grid h-full place-items-center p-6">
      <div className="max-w-[440px] text-center">
        <span className="mx-auto grid h-11 w-11 place-items-center rounded-full bg-surface-2 text-ink-2">
          <ClipboardList className="h-5 w-5" aria-hidden />
        </span>
        <h2 className="mt-4 text-[15px] font-bold text-ink">진료 지원 AI에 연 환자가 없습니다</h2>
        <p className="mt-2 text-[13px] leading-6 text-ink-2">
          내 담당 환자에서 환자를 고르고 차트의 '유사 사례 찾기'를 누르면, 진료 지원 AI가 비슷한 과거 사례를 찾아 이 화면에 보여 줍니다.
        </p>
        <NavLink to="/emr" className="btn-primary mt-5 inline-flex h-10 px-4">
          내 담당 환자 보기
        </NavLink>
      </div>
    </div>
  );
}
