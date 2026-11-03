import { BarChart3, BookOpen, History, ListChecks, Radar, ShieldCheck, Stethoscope, type LucideIcon } from 'lucide-react';

export type Role = 'clinician' | 'security';

export interface NavItem {
  to: string;
  label: string;
  title: string;
  icon: LucideIcon;
  end?: boolean;
}

export const NAV: Record<Role, NavItem[]> = {
  clinician: [
    { to: '/', label: '진료', title: '유사 사례 조회', icon: Stethoscope, end: true },
    { to: '/history', label: '조회 기록', title: '조회 기록', icon: History },
    { to: '/policy', label: '보호 정책', title: '보호 정책', icon: ShieldCheck },
  ],
  security: [
    { to: '/monitor', label: '관제', title: '실시간 관제', icon: Radar },
    { to: '/report', label: '리포트', title: '레드팀 점검 리포트', icon: BarChart3 },
    { to: '/audit', label: '감사 기록', title: '감사 기록', icon: ListChecks },
    { to: '/terms', label: '용어', title: '의료 용어 사전', icon: BookOpen },
    { to: '/policy', label: '보호 정책', title: '보호 정책', icon: ShieldCheck },
  ],
};

export const ROLE_HOME: Record<Role, string> = { clinician: '/', security: '/monitor' };
export const ROLE_LABEL: Record<Role, string> = { clinician: '의료진', security: '보안 담당자' };

export function roleOfPath(path: string): Role | null {
  if (path === '/' || path.startsWith('/history')) return 'clinician';
  if (path.startsWith('/monitor') || path.startsWith('/report') || path.startsWith('/audit') || path.startsWith('/terms')) return 'security';
  return null;
}
