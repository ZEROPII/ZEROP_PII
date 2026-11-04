import { useEffect, useRef, useState } from 'react';
import { Navigate, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { apiMode } from '../../api';
import { LoginPage } from '../../pages/LoginPage';
import { useAuth } from '../../state/AuthContext';
import { ClinicMessagesProvider } from '../../state/ClinicMessages';
import { TermProvider } from '../../state/TermContext';
import { WorkspaceProvider } from '../../state/WorkspaceContext';
import { TermDrawer } from '../terminology/TermDrawer';
import { TermHoverCard } from '../terminology/TermHoverCard';
import { LogoMark } from '../brand/Logo';
import { ClinicianShell } from './ClinicianShell';
import { CommandPalette } from './CommandPalette';
import { NAV, PRODUCT_HOME, roleOfPath, type Role } from './nav';
import { TopBar } from './TopBar';

function storedRole(): Role {
  try {
    return localStorage.getItem('zp-role') === 'security' ? 'security' : 'clinician';
  } catch {
    return 'clinician';
  }
}

/** 보안 담당자 화면 틀 (MediCloak 관제): 왼쪽 메뉴 레일과 위 머리줄 */
function SecurityShell({ role, product, onOpenPalette }: { role: Role; product: boolean; onOpenPalette(): void }) {
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
        <TopBar role={role} product={product} title={current.title} onOpenPalette={onOpenPalette} />
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

function BootScreen() {
  return (
    <div className="grid h-dvh place-items-center bg-page text-ink-3" role="status" aria-live="polite">
      <span className="inline-flex items-center gap-3 text-[13px]">
        <LogoMark size={28} />
        MediCloak을 여는 중
      </span>
    </div>
  );
}

/**
 * 역할에 따라 전혀 다른 두 화면을 보여 준다.
 *   의료진: 병원 EMR 안의 진료 지원 AI (청록 토큰, data-app="emr"). 재식별 위험 숫자 없음.
 *   보안 담당자: MediCloak 관제 (남색 토큰). 후보 수 · 판정 근거 · 단서 그래프 · 감사 기록.
 * 운영 모드(python -m medicloak)에서는 로그인한 계정의 역할이 화면을 정하고, 다른 역할 화면 주소로 오면 자기 처음 화면으로 보낸다.
 * 데모 모드에서는 화면 전환 단추와 주소로 역할을 바꾼다.
 */
export function AppLayout() {
  const auth = useAuth();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const fixed: Role | null = auth.status === 'user' && auth.user ? auth.user.role : null;
  const pathRole = roleOfPath(pathname);
  // 역할은 그리는 그 자리에서 정한다. 효과(useEffect)로 나중에 바꾸면, 화면 전환 직후 첫 그림이
  // 이전 역할의 틀 안에서 그려져 의료진 화면 부품이 제공자 밖에 놓인다 (화면이 비는 오류).
  const [fallback, setFallback] = useState<Role>(storedRole);
  const role: Role = fixed ?? pathRole ?? fallback;
  const [paletteOpen, setPaletteOpen] = useState(false);
  const prevStatus = useRef(auth.status);

  useEffect(() => {
    if (fixed) return;
    setFallback(role);
    try {
      localStorage.setItem('zp-role', role);
    } catch {
      /* 저장 못 해도 동작 */
    }
  }, [role, fixed]);

  // 막 로그인했으면 그 역할의 처음 화면으로 (의료진은 EMR 외래 목록부터)
  useEffect(() => {
    if (prevStatus.current === 'anon' && auth.status === 'user' && auth.user) navigate(PRODUCT_HOME[auth.user.role], { replace: true });
    prevStatus.current = auth.status;
  }, [auth.status, auth.user, navigate]);

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

  if (auth.status === 'loading') return <BootScreen />;
  if (auth.status === 'anon') return <LoginPage />;
  if (fixed && pathRole && pathRole !== fixed) return <Navigate to={PRODUCT_HOME[fixed]} replace />;

  const product = auth.status === 'user';
  const palette = paletteOpen && <CommandPalette role={role} onClose={() => setPaletteOpen(false)} />;
  const open = () => setPaletteOpen(true);

  return (
    <TermProvider view={role === 'security' ? 'security' : 'clinician'}>
      {role === 'clinician' ? (
        // 의료진 화면 API(숫자 없음)는 의료진 틀 안에서만 부른다. 보안 담당자 계정은 이 API를 쓸 수 없다 (403)
        <WorkspaceProvider>
          <ClinicMessagesProvider enabled>
            {/* display: contents라 상자는 없고, 안쪽 모든 요소(대화상자 · 용어 패널 포함)가 의료진 토큰을 물려받는다 */}
            <div data-app="emr" className="contents">
              <ClinicianShell role={role} product={product} onOpenPalette={open} />
              {palette}
              <TermDrawer />
              <TermHoverCard />
            </div>
          </ClinicMessagesProvider>
        </WorkspaceProvider>
      ) : (
        <>
          <SecurityShell role={role} product={product} onOpenPalette={open} />
          {palette}
          <TermDrawer />
          <TermHoverCard />
        </>
      )}
    </TermProvider>
  );
}
