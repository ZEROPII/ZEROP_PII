import type { PolicyDecisionState, PrivacyAction, RiskLevel } from '../types/domain';

/** 위험 수준 색상. 문구는 백엔드 statusLabel을 쓰고, 여기서는 색만 고른다. */
export const RISK_TONE: Record<RiskLevel, { badge: string; bar: string; dot: string; text: string; fallbackLabel: string }> = {
  safe: { badge: 'bg-emerald-50 text-emerald-700 ring-emerald-200', bar: 'bg-emerald-500', dot: 'bg-emerald-500', text: 'text-emerald-700', fallbackLabel: '안전' },
  caution: { badge: 'bg-amber-50 text-amber-700 ring-amber-200', bar: 'bg-amber-500', dot: 'bg-amber-500', text: 'text-amber-700', fallbackLabel: '주의' },
  blocked: { badge: 'bg-red-50 text-red-700 ring-red-200', bar: 'bg-red-500', dot: 'bg-red-500', text: 'text-red-700', fallbackLabel: '제한' },
  danger: { badge: 'bg-red-100 text-red-800 ring-red-300', bar: 'bg-red-600', dot: 'bg-red-600', text: 'text-red-800', fallbackLabel: '위험' },
};

export const ACTION_META: Record<PrivacyAction, { label: string; badge: string }> = {
  allow: { label: '그대로', badge: 'bg-blue-50 text-blue-700 ring-blue-200' },
  generalize: { label: '넓힘', badge: 'bg-blue-600 text-white ring-blue-600' },
  suppress: { label: '비공개', badge: 'bg-slate-200 text-slate-700 ring-slate-300' },
};

export const DECISION_LABEL: Record<PolicyDecisionState, string> = {
  allow: '그대로 공개 허용',
  generalize: '일반화 후 공개',
  suppress: '비공개',
  restrict: '추가 공개 제한',
};
