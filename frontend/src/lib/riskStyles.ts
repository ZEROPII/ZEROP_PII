import type { PolicyDecisionState, PrivacyAction, RiskLevel } from '../types/domain';

export type Tone = 'safe' | 'caution' | 'danger' | 'brand' | 'plain';

/** 상태 칩 색 (Zero PII 토큰). 상태는 항상 모양 아이콘 + 글자 + 색으로 함께 보여 준다. */
export const TONE_CHIP: Record<Tone, string> = {
  safe: 'bg-safe-tint text-safe-text',
  caution: 'bg-caution-tint text-caution-text',
  danger: 'bg-danger-tint text-danger-text',
  brand: 'bg-iris-tint text-iris-text',
  plain: 'bg-surface-2 text-ink-2',
};

/** 위험 수준 색. 문구는 백엔드 statusLabel을 쓰고, 여기서는 색만 고른다. */
export const RISK_TONE: Record<RiskLevel, { tone: Tone; bar: string; dot: string; text: string; fallbackLabel: string }> = {
  safe: { tone: 'safe', bar: 'bg-safe', dot: 'bg-safe', text: 'text-safe-text', fallbackLabel: '여유' },
  caution: { tone: 'caution', bar: 'bg-caution', dot: 'bg-caution', text: 'text-caution-text', fallbackLabel: '주의' },
  blocked: { tone: 'danger', bar: 'bg-danger', dot: 'bg-danger', text: 'text-danger-text', fallbackLabel: '제한' },
  danger: { tone: 'danger', bar: 'bg-danger', dot: 'bg-danger', text: 'text-danger-text', fallbackLabel: '위험' },
};

/** 공개 조치 표시: 허용(안전 원) · 일반화(주의 마름모) · 가림(위험 삼각형). */
export const ACTION_META: Record<PrivacyAction, { label: string; tone: Tone; help: string }> = {
  allow: { label: '허용', tone: 'safe', help: '그대로 답했습니다 (후보가 기준보다 많음).' },
  generalize: { label: '일반화', tone: 'caution', help: '한 단계 넓은 범주로 바꿔 답했습니다.' },
  suppress: { label: '가림', tone: 'danger', help: '이 값은 가리고 답했습니다 (그대로면 후보가 너무 적어짐).' },
};

export const DECISION_LABEL: Record<PolicyDecisionState, string> = {
  allow: '그대로 공개 허용',
  generalize: '일반화 후 공개',
  suppress: '가림',
  restrict: '추가 공개 제한',
};
