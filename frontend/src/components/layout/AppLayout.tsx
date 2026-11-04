import { useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { apiMode } from '../../api';
import { ClinicMessagesProvider } from '../../state/ClinicMessages';
import { TermProvider } from '../../state/TermContext';
import { TermDrawer } from '../terminology/TermDrawer';
import { TermHoverCard } from '../terminology/TermHoverCard';
import { LogoMark } from '../brand/Logo';
import { ClinicianShell } from './ClinicianShell';
import { CommandPalette } from './CommandPalette';
import { NAV, roleOfPath, type Role } from './nav';
import { TopBar } from './TopBar';

function storedRole(): Role {
  try {
    return localStorage.getItem('zp-role') === 'security' ? 'security' : 'clinician';
  } catch {
    return 'clinician';
  }
}

/** 보안 담당자 화면 틀 (MediCloak 관제): 왼쪽 메뉴 레일과 위 머리줄 */
function SecurityShell({ role, onOpenPalette }: { role: Role; onOpenPalette(): void }) {
  const { pathname } = useLocation();
  const items = NAV.security;
  const current = items.find((i) => (i.end ? pathname === i.to : pathname.startsWith(i.to))) ?? items[0];
  return (
    <div className="flex h-dvh flex-col bg-page text-ink md:flex-row">
      <nav aria-label="주 메뉴" className="hidden w-[76px] shrink-0 flex-col items-center gap-1.5 border-r border-line bg-surface py-[18px] md:flex">
        <NavLink to="/monitor" className="mb-4 rounded-control" aria-label="MediCloak 관제 처음 화면">
          <LogoMark size={34} />
        </NavLink>
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              `flex w-[60px] flex-col items-center gap-1 rounded-control pb-1.5 pt-2 text-center text-[11px] font-semibold leading-tight transition-colors ${
                isActive ? 'bg-iris-tint text-iris-text' : 'text-ink-3 hover:bg-surface-2 hover:text-ink'
              }`
            }
          >
            <item.icon className="h-[22px] w-[22px]" strokeWidth={1.8} aria-hidden />
            {item.label}
          </NavLink>
        ))}
      </nav>

      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <TopBar role={role} title={current.title} onOpenPalette={onOpenPalette} />
        {apiMode === 'mock' && (
          <p className="shrink-0 border-b border-line bg-caution-tint px-4 py-1.5 text-center text-xs text-caution-text">
            예시 데이터로 동작 중입니다. 사례와 후보 수는 화면 확인용이며 실험 결과가 아닙니다.
          </p>
        )}
        <main className="min-h-0 flex-1">
          <Outlet />
        </main>
        {/* 좁은 화면: 레일 대신 아래 탭 */}
        <nav aria-label="주 메뉴" className="flex shrink-0 overflow-x-auto border-t border-line bg-surface md:hidden">
          {items.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => `flex min-w-[64px] flex-1 flex-col items-center gap-0.5 py-2 text-[11px] font-semibold ${isActive ? 'text-iris-text' : 'text-ink-3'}`}
            >
              <item.icon className="h-5 w-5" strokeWidth={1.8} aria-hidden />
              {item.label}
            </NavLink>
          ))}
        </nav>
      </div>
    </div>
  );
}

/**
 * 역할에 따라 전혀 다른 두 화면을 보여 준다.
 *   의료진: 병원 EMR 안의 진료 지원 AI (청록 토큰, data-app="emr"). 재식별 위험 숫자 없음.
 *   보안 담당자: MediCloak 관제 (남색 토큰). 후보 수 · 판정 근거 · 단서 그래프 · 감사 기록.
 */
export function AppLayout() {
  const { pathname } = useLocation();
  const [role, setRole] = useState<Role>(() => roleOfPath(pathname) ?? storedRole());
  const [paletteOpen, setPaletteOpen] = useState(false);

  useEffect(() => {
    const r = roleOfPath(pathname);
    if (r && r !== role) setRole(r);
  }, [pathname, role]);

  useEffect(() => {
    try {
      localStorage.setItem('zp-role', role);
    } catch {
      /* 저장 못 해도 동작 */
    }
  }, [role]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const palette = paletteOpen && <CommandPalette role={role} onClose={() => setPaletteOpen(false)} />;

  return (
    <TermProvider view={role === 'security' ? 'security' : 'clinician'}>
      {/* display: contents라 상자는 없고, 안쪽 모든 요소(대화상자 · 용어 패널 포함)가 의료진 토큰을 물려받는다 */}
      <div data-app={role === 'clinician' ? 'emr' : undefined} className="contents">
        {role === 'clinician' ? (
          <ClinicMessagesProvider>
            <ClinicianShell role={role} onOpenPalette={() => setPaletteOpen(true)} />
            {palette}
          </ClinicMessagesProvider>
        ) : (
          <>
            <SecurityShell role={role} onOpenPalette={() => setPaletteOpen(true)} />
            {palette}
          </>
        )}
        <TermDrawer />
        <TermHoverCard />
      </div>
    </TermProvider>
  );
}
