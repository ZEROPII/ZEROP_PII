import { BookOpen, CornerDownLeft, FileText, MessagesSquare, Search } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { monitorApi } from '../../api/monitorApi';
import { terminologyApi } from '../../api/terminologyApi';
import { useTerms } from '../../state/TermContext';
import { useWorkspace } from '../../state/WorkspaceContext';
import type { TermSummary } from '../../types/terminology';
import type { MonitorRow } from '../../types/monitor';
import { NAV, type Role } from './nav';

interface Item {
  id: string;
  label: string;
  hint: string;
  run(): void;
  icon?: typeof Search;
}

/**
 * ⌘K 명령 찾기. 위아래 화살표로 고르고 Enter로 엽니다.
 *   의료진: 진료 화면 이동, 사례 열기, 의료 용어 찾기 (관제 목록은 불러오지 않는다)
 *   보안 담당자: 관제 화면 이동, 대화 번호로 관제 상세 열기, 의료 용어 찾기
 */
export function CommandPalette({ role, onClose }: { role: Role; onClose(): void }) {
  const navigate = useNavigate();
  const { state, actions } = useWorkspace();
  const cases = state.cases.data;
  const [q, setQ] = useState('');
  const [active, setActive] = useState(0);
  const [rows, setRows] = useState<MonitorRow[]>([]);
  const [terms, setTerms] = useState<TermSummary[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const { view, openTerm, openSearch } = useTerms();

  useEffect(() => {
    const t = q.trim();
    if (t.length < 2) {
      setTerms([]);
      return;
    }
    const ctl = new AbortController();
    const timer = window.setTimeout(() => terminologyApi.search(t, { limit: 5, view }, ctl.signal).then(setTerms, () => setTerms([])), 180);
    return () => {
      window.clearTimeout(timer);
      ctl.abort();
    };
  }, [q, view]);

  useEffect(() => {
    inputRef.current?.focus();
    if (role !== 'security') return;
    const ctl = new AbortController();
    monitorApi.overview(ctl.signal).then((o) => setRows(o.sessions), () => undefined);
    return () => ctl.abort();
  }, [role]);

  const items = useMemo<Item[]>(() => {
    const pages: Item[] = NAV[role].map((n) => ({ id: `page:${n.to}`, label: n.title, hint: '화면', icon: n.icon, run: () => navigate(n.to) }));
    const convs: Item[] =
      role === 'security'
        ? rows.map((r) => ({
            id: `conv:${r.id}`,
            label: `${r.trial_id} ${r.status_label}`,
            hint: `${r.source_label} ${r.turns}턴`,
            icon: MessagesSquare,
            run: () => navigate(`/monitor?s=${encodeURIComponent(r.id)}`),
          }))
        : (cases ?? []).map((c) => ({
            id: `case:${c.caseId}`,
            label: `${c.label} ${c.diagnosis}`,
            hint: '사례 열기',
            icon: FileText,
            run: () => {
              actions.selectCase(c.caseId);
              navigate('/');
            },
          }));
    const all = [...pages, ...convs];
    const t = q.trim().toLowerCase();
    if (!t) return all;
    const termItems: Item[] = terms.map((x) => ({
      id: `term:${x.node_id}`,
      label: x.canonical_label,
      hint: `의료 용어 · ${x.attribute_label}`,
      icon: BookOpen,
      run: () => openTerm(x.node_id),
    }));
    const lookup: Item = { id: 'term-search', label: `'${q.trim()}' 의료 용어 패널에서 찾기`, hint: '의료 용어', icon: BookOpen, run: () => openSearch(q.trim()) };
    return [...all.filter((i) => `${i.label} ${i.hint}`.toLowerCase().includes(t)), ...termItems, lookup];
  }, [q, rows, terms, navigate, openTerm, openSearch, role, cases, actions]);

  useEffect(() => setActive(0), [q]);

  function onKey(e: React.KeyboardEvent) {
    if (e.key === 'Escape') onClose();
    else if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, items.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === 'Enter' && items[active]) {
      e.preventDefault();
      items[active].run();
      onClose();
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-scrim px-4 pt-[12vh]" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-modal="true" aria-label="명령 찾기" className="w-full max-w-[560px] overflow-hidden rounded-overlay bg-surface shadow-overlay" onKeyDown={onKey}>
        <div className="flex items-center gap-2.5 border-b border-line px-4 py-3.5">
          <Search className="h-4 w-4 text-ink-3" aria-hidden />
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={role === 'security' ? '화면 이름, 대화 번호(T0014), 의료 용어를 입력하세요' : '화면 이름, 사례, 의료 용어를 입력하세요'}
            className="flex-1 bg-transparent text-[15px] text-ink outline-none placeholder:text-ink-3"
            aria-label="찾을 내용"
          />
          <span className="kbd">esc</span>
        </div>
        <ul role="listbox" className="scroll-thin max-h-[52vh] overflow-y-auto p-1.5">
          {items.length === 0 && <li className="px-3 py-6 text-center text-[13px] text-ink-3">맞는 항목이 없습니다.</li>}
          {items.map((it, i) => (
            <li key={it.id} role="option" aria-selected={i === active}>
              <button
                type="button"
                onMouseEnter={() => setActive(i)}
                onClick={() => {
                  it.run();
                  onClose();
                }}
                className={`flex w-full items-center gap-2.5 rounded-control px-2.5 py-2 text-left text-[13px] ${i === active ? 'bg-iris-tint' : ''}`}
              >
                <span className="grid h-[22px] w-[22px] place-items-center rounded-[6px] bg-surface-2 text-ink-2">
                  {it.icon ? <it.icon className="h-3.5 w-3.5" aria-hidden /> : null}
                </span>
                <span className="flex-1 truncate font-medium text-ink">{it.label}</span>
                <span className="text-xs text-ink-3">{it.hint}</span>
                {i === active && <CornerDownLeft className="h-3.5 w-3.5 text-ink-3" aria-hidden />}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
