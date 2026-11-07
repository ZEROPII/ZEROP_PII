// 의료 용어 도우미 상태: 옆 패널(열림 · 고른 용어 · 검색어), 답변 속 용어 자동 표시 켜기/끄기, 마우스를 올렸을 때 뜨는 요약.
// 보기(view)는 화면 역할에서 온다: 보안 담당자 = security(기준 집단 환자 수 포함), 의료진 = clinician.

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { terminologyApi } from '../api/terminologyApi';
import type { TermMention, TermStatus, TermSummary, TermView } from '../types/terminology';

interface HoverState {
  nodeId: string;
  rect: { left: number; top: number; bottom: number; width: number };
}

interface TermContextValue {
  view: TermView;
  status: TermStatus | null;
  /** 답변 속 용어 자동 표시 (밑줄 · 용어 칩) */
  auto: boolean;
  setAuto(on: boolean): void;
  drawerOpen: boolean;
  selected: string | null;
  query: string;
  openTerm(nodeId: string): void;
  openSearch(query?: string): void;
  closeDrawer(): void;
  toggleDrawer(): void;
  /** 자동 표시로 받아 둔 요약 (마우스 올림 요약 · 칩 이름에 씀) */
  summaries: Map<string, TermSummary>;
  remember(terms: Record<string, TermSummary>): void;
  hover: HoverState | null;
  showHover(nodeId: string, el: HTMLElement): void;
  hideHover(): void;
}

const Ctx = createContext<TermContextValue | null>(null);
const AUTO_KEY = 'zp-terms-auto';

function storedAuto(): boolean {
  try {
    return localStorage.getItem(AUTO_KEY) !== 'off';
  } catch {
    return true;
  }
}

export function TermProvider({ view, children }: { view: TermView; children: ReactNode }) {
  const [status, setStatus] = useState<TermStatus | null>(null);
  const [auto, setAutoState] = useState(storedAuto);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [summaryVersion, setSummaryVersion] = useState(0);
  const [hover, setHover] = useState<HoverState | null>(null);
  const hoverTimer = useRef<number | undefined>(undefined);

  useEffect(() => {
    const ctl = new AbortController();
    terminologyApi.status(ctl.signal).then(setStatus, () => setStatus({ available: false, generated: false, build_command: 'python scripts/build_terminology_db.py' }));
    return () => ctl.abort();
  }, []);

  const setAuto = useCallback((on: boolean) => {
    setAutoState(on);
    try {
      localStorage.setItem(AUTO_KEY, on ? 'on' : 'off');
    } catch {
      /* 저장 못 해도 동작 */
    }
  }, []);

  // 요약은 보기별로 따로 둔다: 의료진 보기 요약에는 환자 수가 없다
  const remember = useCallback(
    (terms: Record<string, TermSummary>) => {
      const m = summaryMap(view);
      const fresh = Object.keys(terms).filter((id) => !m.has(id));
      if (!fresh.length) return;
      for (const id of fresh) m.set(id, terms[id]);
      setSummaryVersion((v) => v + 1);
    },
    [view],
  );
  const summaries = useMemo(() => new Map(summaryMap(view)), [view, summaryVersion]);

  const showHover = useCallback((nodeId: string, el: HTMLElement) => {
    window.clearTimeout(hoverTimer.current);
    hoverTimer.current = window.setTimeout(() => {
      const r = el.getBoundingClientRect();
      setHover({ nodeId, rect: { left: r.left, top: r.top, bottom: r.bottom, width: r.width } });
    }, 220);
  }, []);
  const hideHover = useCallback(() => {
    window.clearTimeout(hoverTimer.current);
    setHover(null);
  }, []);

  const value = useMemo<TermContextValue>(
    () => ({
      view,
      status,
      auto,
      setAuto,
      drawerOpen,
      selected,
      query,
      openTerm: (nodeId) => {
        setSelected(nodeId);
        setDrawerOpen(true);
        setHover(null);
      },
      openSearch: (q) => {
        setSelected(null);
        if (q !== undefined) setQuery(q);
        setDrawerOpen(true);
      },
      closeDrawer: () => setDrawerOpen(false),
      toggleDrawer: () => setDrawerOpen((o) => !o),
      summaries,
      remember,
      hover,
      showHover,
      hideHover,
    }),
    [view, status, auto, setAuto, drawerOpen, selected, query, summaries, remember, hover, showHover, hideHover],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useTerms(): TermContextValue {
  const v = useContext(Ctx);
  if (!v) throw new Error('useTerms는 TermProvider 안에서만 쓸 수 있습니다.');
  return v;
}

// ── 답변 속 용어 찾기 (글 단위로 한 번만 묻고 기억) ─────────────────────────
const cache = new Map<string, TermMention[]>();
const summaryMaps: Record<TermView, Map<string, TermSummary>> = { security: new Map(), clinician: new Map() };
function summaryMap(view: TermView): Map<string, TermSummary> {
  return summaryMaps[view];
}
const cacheKey = (view: TermView, text: string) => `${view}\u0000${text}`;

/** texts 각각의 용어 위치. 자동 표시가 꺼져 있거나 용어 DB가 없으면 빈 결과. */
export function useTermDetect(texts: string[]): { mentions: (TermMention[] | undefined)[]; ready: boolean } {
  const { view, auto, status, remember } = useTerms();
  const [, setVersion] = useState(0);
  const enabled = auto && !!status?.available;
  const key = texts.join('\u0001');

  useEffect(() => {
    if (!enabled) return;
    const todo = [...new Set(texts.filter((t) => t.trim() && !cache.has(cacheKey(view, t))))];
    if (!todo.length) return;
    const ctl = new AbortController();
    terminologyApi.detect(todo, view, ctl.signal).then(
      (res) => {
        todo.forEach((t, i) => cache.set(cacheKey(view, t), res.mentions[i] ?? []));
        remember(res.terms);
        setVersion((v) => v + 1);
      },
      () => undefined,
    );
    return () => ctl.abort();
    // texts는 key로 비교한다
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, view, enabled, remember]);

  if (!enabled) return { mentions: texts.map(() => undefined), ready: false };
  const mentions = texts.map((t) => cache.get(cacheKey(view, t)));
  return { mentions, ready: mentions.every((m, i) => m !== undefined || !texts[i].trim()) };
}

/** 테스트용 */
export function clearTermCache(): void {
  cache.clear();
  summaryMaps.security.clear();
  summaryMaps.clinician.clear();
}
