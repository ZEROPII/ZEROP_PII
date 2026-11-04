import { BarChart3, BookOpen, History, ListChecks, MessagesSquare, Radar, ShieldCheck, Stethoscope, type LucideIcon } from 'lucide-react';

export type Role = 'clinician' | 'security';

export interface NavItem {
  to: string;
  label: string;
  title: string;
  icon: LucideIcon;
  end?: boolean;
}

/**
 * 의료진 화면은 병원 EMR에 들어간 진료 지원 AI다. 재식별 위험 숫자 · 후보 렌즈 · 판정 근거는 보안 담당자 화면에만 둔다.
 * 보호 정책(기준값)도 보안 담당자 화면으로 옮기고, 의료진에게는 숫자 없이 쉬운 말로 쓴 '보호 안내'를 둔다.
 */
export const NAV: Record<Role, NavItem[]> = {
  clinician: [
    { to: '/', label: '사례 조회', title: '유사 사례 조회', icon: Stethoscope, end: true },
    { to: '/history', label: '조회 기록', title: '조회 기록', icon: History },
    { to: '/guide', label: '보호 안내', title: '개인정보 보호 안내', icon: ShieldCheck },
  ],
  security: [
    { to: '/monitor', label: '관제', title: '실시간 관제', icon: Radar },
    { to: '/watch', label: '의료진 대화', title: '의료진 대화 위험 분석', icon: MessagesSquare },
    { to: '/report', label: '리포트', title: '레드팀 점검 리포트', icon: BarChart3 },
    { to: '/audit', label: '감사 기록', title: '감사 기록', icon: ListChecks },
    { to: '/terms', label: '용어', title: '의료 용어 사전', icon: BookOpen },
    { to: '/policy', label: '보호 정책', title: '보호 정책', icon: ShieldCheck },
  ],
};

export const ROLE_HOME: Record<Role, string> = { clinician: '/', security: '/monitor' };
export const ROLE_LABEL: Record<Role, string> = { clinician: '의료진', security: '보안 담당자' };

export function roleOfPath(path: string): Role | null {
  if (path === '/' || path.startsWith('/history') || path.startsWith('/guide')) return 'clinician';
  if (['/monitor', '/watch', '/report', '/audit', '/terms', '/policy'].some((p) => path.startsWith(p))) return 'security';
  return null;
}
