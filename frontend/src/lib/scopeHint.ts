// 묻는 범위 안내: 질문 문장이 가리키는 사례와 지금 묻는 범위가 다르면 보내기 전에 알린다 (ADR-0029).
// 의료진 체험(2026-11-05): 범위가 '사례 1'인데 "이 사례들에서…"라고 물으면 아무 안내 없이 사례 1만 답했다.
import type { QuestionScope } from '../types/domain';

/** 질문 문장에 나온 사례 번호 ("사례1", "사례 3", "2번 사례") */
const CASE_NO = /사례\s*0*(\d{1,2})(?!\d)|(\d{1,2})\s*번\s*사례/g;
/** 여러 사례를 함께 가리키는 말 ("사례 1, 2" · "사례 1~3"처럼 번호를 이어 쓴 것 포함) */
const MANY =
  /(?:모든|전체|각|여러|다른|찾은)\s*사례|사례\s*(?:전체|모두|전부|마다|별|들|중)|공통|(?:\d+|두|세|네|다섯)\s*(?:개|건)\s*(?:의\s*)?사례|사례\s*\d+\s*(?:[,·~\-]|와|과|및|하고)\s*\d/;

export type ScopeHint =
  /** 범위는 사례 하나인데 질문은 여러 사례를 묻는다 */
  | { kind: 'toAll'; hold: true }
  /** 범위는 사례 하나인데 질문은 다른 사례 하나를 묻는다 */
  | { kind: 'otherCase'; caseNo: number; hold: true }
  /** 범위는 전체인데 질문은 사례 하나만 묻는다 (보내도 되지만 그 사례 대화에 남기는 쪽을 권한다) */
  | { kind: 'oneCase'; caseNo: number; hold: false };

export function caseNumbers(text: string, total: number): number[] {
  const out = new Set<number>();
  for (const m of text.matchAll(CASE_NO)) {
    const n = Number(m[1] ?? m[2]);
    if (n >= 1 && n <= total) out.add(n);
  }
  return [...out].sort((a, b) => a - b);
}

/** 사례 이름표("사례 3")의 번호 */
export function caseNoOf(label: string | undefined | null): number | null {
  const m = label?.match(/(\d{1,2})/);
  return m ? Number(m[1]) : null;
}

/**
 * 질문과 범위가 어긋나면 안내 종류를 돌려준다. 어긋나지 않거나 판단할 수 없으면 null.
 * current: 지금 고른 사례 번호, total: 찾은 사례 수
 */
export function scopeHint(text: string, scope: QuestionScope, current: number | null, total: number): ScopeHint | null {
  const q = text.trim();
  if (q.length < 4 || total < 2) return null;
  const nums = caseNumbers(q, total);
  const many = MANY.test(q) || nums.length >= 2;
  if (scope === 'case') {
    if (many) return { kind: 'toAll', hold: true };
    if (nums.length === 1 && current !== null && nums[0] !== current) return { kind: 'otherCase', caseNo: nums[0], hold: true };
    return null;
  }
  if (!many && nums.length === 1) return { kind: 'oneCase', caseNo: nums[0], hold: false };
  return null;
}
