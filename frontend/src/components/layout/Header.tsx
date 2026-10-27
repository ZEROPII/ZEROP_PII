import { Activity, Stethoscope } from 'lucide-react';
import { NavLink } from 'react-router-dom';
import { useWorkspace } from '../../state/WorkspaceContext';
import { ProtectionBadge } from './ProtectionBadge';

const NAV_ITEMS = [
  { to: '/', label: '유사 사례 조회', end: true },
  { to: '/history', label: '조회 기록', end: false },
  { to: '/policy', label: '보호 정책', end: false },
];

export function Header() {
  const { state } = useWorkspace();
  const env = state.environment.data;

  return (
    <header className="shrink-0 bg-navy-900 text-white">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 px-4 py-2 md:h-14 md:flex-nowrap md:py-0">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-blue-600">
            <Activity className="h-[18px] w-[18px]" aria-hidden />
          </span>
          <p className="truncate text-sm font-semibold tracking-tight">
            ZEROOP2 <span className="mx-1 text-slate-400">|</span>
            <span className="font-medium text-slate-200">Clinical Case Finder</span>
          </p>
        </div>

        <nav aria-label="주 메뉴" className="order-3 -mx-1 flex w-full gap-1 overflow-x-auto md:order-none md:mx-0 md:w-auto md:self-stretch">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `relative flex items-center whitespace-nowrap rounded-md px-3 py-1.5 text-[13px] transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400 md:rounded-none md:py-0 ${
                  isActive
                    ? 'bg-white/10 font-semibold text-white md:bg-transparent md:after:absolute md:after:inset-x-2 md:after:bottom-0 md:after:h-[3px] md:after:rounded-t md:after:bg-blue-500'
                    : 'text-slate-300 hover:bg-white/5 hover:text-white'
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="ml-auto flex min-w-0 items-center gap-3">
          <ProtectionBadge policy={state.policy} />
          {env && (
            <span className="hidden items-center gap-1.5 whitespace-nowrap text-xs text-slate-300 lg:inline-flex" title={env.roleLabel}>
              <Stethoscope className="h-3.5 w-3.5" aria-hidden />
              {env.locationLabel}
            </span>
          )}
        </div>
      </div>
    </header>
  );
}
