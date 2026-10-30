import { Gauge, MessageSquare, Users } from 'lucide-react';
import { useState } from 'react';
import { CaseList } from '../components/cases/CaseList';
import { ChatPanel } from '../components/chat/ChatPanel';
import { DisclosureHistoryPanel } from '../components/disclosure/DisclosureHistoryPanel';
import { ProtectionBadge } from '../components/layout/ProtectionBadge';
import { PatientContextCard } from '../components/patient/PatientContextCard';
import { RiskPanel } from '../components/risk/RiskPanel';
import { useSelectedCase, useWorkspace } from '../state/WorkspaceContext';

type PanelTab = 'cases' | 'chat' | 'risk';

const TABS: { id: PanelTab; label: string; icon: typeof Users }[] = [
  { id: 'cases', label: '환자와 사례', icon: Users },
  { id: 'chat', label: '대화', icon: MessageSquare },
  { id: 'risk', label: '위험', icon: Gauge },
];

/** 넓은 화면은 3단, 좁은 화면(lg 미만)은 탭으로 한 영역씩 보여 준다. */
export function CaseFinderPage() {
  const [tab, setTab] = useState<PanelTab>('chat');
  const { summary } = useSelectedCase();
  const { state } = useWorkspace();
  const panelClass = (id: PanelTab) => `${tab === id ? 'flex' : 'hidden'} lg:flex min-h-0 flex-col gap-3`;

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 px-4 pt-3 md:px-6">
        <p className="text-[13px] text-ink-2">
          비슷한 과거 사례를 AI에게 물어보세요. 답에서 환자를 좁힐 수 있는 값은 자동으로 넓히거나 가립니다.
        </p>
        <span className="ml-auto">
          <ProtectionBadge policy={state.policy} />
        </span>
      </div>
      <div role="tablist" aria-label="화면 영역" className="mt-2 flex shrink-0 gap-1 border-b border-line px-2 lg:hidden">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            role="tab"
            type="button"
            id={`tab-${id}`}
            aria-selected={tab === id}
            aria-controls={`panel-${id}`}
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

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 p-3 md:px-6 md:pb-6 lg:grid-cols-[280px_minmax(420px,1fr)_300px]">
        <aside id="panel-cases" aria-label="환자 정보와 비슷한 사례" className={`${panelClass('cases')} scroll-thin overflow-y-auto`}>
          <PatientContextCard />
          <CaseList onSelected={() => setTab('chat')} />
        </aside>

        <section id="panel-chat" aria-label="AI 대화" className={panelClass('chat')}>
          <ChatPanel />
        </section>

        <aside id="panel-risk" aria-label="재식별 위험과 나간 정보" className={`${panelClass('risk')} scroll-thin overflow-y-auto`}>
          <RiskPanel />
          <DisclosureHistoryPanel />
        </aside>
      </div>
    </div>
  );
}
