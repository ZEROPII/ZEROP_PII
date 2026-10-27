import { Gauge, MessageSquare, Users } from 'lucide-react';
import { useState } from 'react';
import { CaseList } from '../components/cases/CaseList';
import { ChatPanel } from '../components/chat/ChatPanel';
import { DisclosureHistoryPanel } from '../components/disclosure/DisclosureHistoryPanel';
import { PatientContextCard } from '../components/patient/PatientContextCard';
import { RiskPanel } from '../components/risk/RiskPanel';
import { useSelectedCase } from '../state/WorkspaceContext';

type PanelTab = 'cases' | 'chat' | 'risk';

const TABS: { id: PanelTab; label: string; icon: typeof Users }[] = [
  { id: 'cases', label: '환자 · 사례', icon: Users },
  { id: 'chat', label: '대화', icon: MessageSquare },
  { id: 'risk', label: '위험 분석', icon: Gauge },
];

/** 데스크톱은 3단, 좁은 화면(lg 미만)은 탭으로 한 패널씩 보여 준다. */
export function CaseFinderPage() {
  const [tab, setTab] = useState<PanelTab>('chat');
  const { summary } = useSelectedCase();
  const panelClass = (id: PanelTab) => `${tab === id ? 'flex' : 'hidden'} lg:flex min-h-0 flex-col gap-3`;

  return (
    <div className="flex h-full flex-col">
      <div role="tablist" aria-label="화면 영역" className="flex shrink-0 gap-1 border-b border-slate-200 bg-white px-2 lg:hidden">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            role="tab"
            type="button"
            id={`tab-${id}`}
            aria-selected={tab === id}
            aria-controls={`panel-${id}`}
            onClick={() => setTab(id)}
            className={`flex flex-1 items-center justify-center gap-1.5 border-b-2 py-2.5 text-xs font-medium ${
              tab === id ? 'border-blue-600 text-blue-700' : 'border-transparent text-slate-500'
            }`}
          >
            <Icon className="h-3.5 w-3.5" aria-hidden />
            {label}
            {id === 'chat' && summary && <span className="hidden text-slate-400 sm:inline">· {summary.label}</span>}
          </button>
        ))}
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 p-3 lg:grid-cols-[250px_minmax(420px,1fr)_270px]">
        <aside id="panel-cases" aria-label="환자 정보와 검색된 사례" className={`${panelClass('cases')} overflow-y-auto`}>
          <PatientContextCard />
          <CaseList onSelected={() => setTab('chat')} />
        </aside>

        <section id="panel-chat" aria-label="AI 대화" className={panelClass('chat')}>
          <ChatPanel />
        </section>

        <aside id="panel-risk" aria-label="재식별 위험과 공개 내역" className={`${panelClass('risk')} overflow-y-auto`}>
          <RiskPanel />
          <DisclosureHistoryPanel />
        </aside>
      </div>
    </div>
  );
}
