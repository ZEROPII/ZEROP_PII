// 기록 종류 · 환자 위험 등급의 색 (index.css 토큰, ADR-0040 · ADR-0041). Tailwind가 이름을 찾게 클래스 이름을 글자 그대로 둔다.

export type ChartKind = 'problems' | 'medications' | 'procedures' | 'carePlans';
export type CellCat = ChartKind | 'visit';

export const KIND_KO: Record<ChartKind, string> = { problems: '진단', medications: '처방', procedures: '시술', carePlans: '관리' };

/** 이름표: 옅은 바탕 + 진한 글자 */
export const KIND_CHIP: Record<ChartKind, string> = {
  problems: 'bg-kind-dx-tint text-kind-dx-text',
  medications: 'bg-kind-rx-tint text-kind-rx-text',
  procedures: 'bg-kind-px-tint text-kind-px-text',
  carePlans: 'bg-kind-care-tint text-kind-care-text',
};

/** 점 · 막대 */
export const KIND_DOT: Record<CellCat, string> = {
  problems: 'bg-kind-dx',
  medications: 'bg-kind-rx',
  procedures: 'bg-kind-px',
  carePlans: 'bg-kind-care',
  visit: 'bg-kind-visit',
};

/** 글자 색 */
export const KIND_TEXT: Record<ChartKind, string> = {
  problems: 'text-kind-dx-text',
  medications: 'text-kind-rx-text',
  procedures: 'text-kind-px-text',
  carePlans: 'text-kind-care-text',
};

/** 내원 달력 칸: 그달 가장 중요한 기록의 색 (진한 칸에 -on 글자), 기록 없이 내원만 한 달은 옅은 칸 */
export const CELL: Record<CellCat, string> = {
  problems: 'bg-kind-dx text-kind-dx-on',
  procedures: 'bg-kind-px text-kind-px-on',
  medications: 'bg-kind-rx text-kind-rx-on',
  carePlans: 'bg-kind-care text-kind-care-on',
  visit: 'bg-kind-visit-tint text-kind-visit-text ring-1 ring-inset ring-kind-visit',
};

export const CELL_KO: Record<CellCat, string> = { problems: '진단', procedures: '시술', medications: '처방', carePlans: '관리', visit: '내원만' };

export type TriageLevel = 1 | 2 | 3 | 4 | 5;

/** 환자 위험 등급: 진한 표시(숫자), 옅은 바탕, 글자 색, 목록 줄 왼쪽 띠 */
export const TRI: Record<TriageLevel, { badge: string; tint: string; text: string; bar: string }> = {
  1: { badge: 'bg-tri-1 text-tri-1-on', tint: 'bg-tri-1-tint', text: 'text-tri-1-text', bar: 'bg-tri-1' },
  2: { badge: 'bg-tri-2 text-tri-2-on', tint: 'bg-tri-2-tint', text: 'text-tri-2-text', bar: 'bg-tri-2' },
  3: { badge: 'bg-tri-3 text-tri-3-on', tint: 'bg-tri-3-tint', text: 'text-tri-3-text', bar: 'bg-tri-3' },
  4: { badge: 'bg-tri-4 text-tri-4-on', tint: 'bg-tri-4-tint', text: 'text-tri-4-text', bar: 'bg-tri-4' },
  5: { badge: 'bg-tri-5 text-tri-5-on', tint: 'bg-tri-5-tint', text: 'text-tri-5-text', bar: 'bg-tri-5' },
};

export const TRI_KO: Record<TriageLevel, string> = { 1: '위급', 2: '높음', 3: '주의', 4: '낮음', 5: '안정' };
