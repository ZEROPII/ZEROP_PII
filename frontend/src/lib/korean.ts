// 한국어 조사 선택 (받침 유무). 영문·숫자로 끝나면 읽는 소리를 대략 따른다.

const NUMBER_HAS_FINAL: Record<string, boolean> = {
  '0': true, '1': true, '2': false, '3': true, '4': false,
  '5': false, '6': true, '7': true, '8': true, '9': false,
};

function hasFinalConsonant(word: string): boolean {
  const last = word.trim().slice(-1);
  if (!last) return false;
  const code = last.charCodeAt(0);
  if (code >= 0xac00 && code <= 0xd7a3) return (code - 0xac00) % 28 !== 0;
  if (last in NUMBER_HAS_FINAL) return NUMBER_HAS_FINAL[last];
  return /[lmnr]/i.test(last);
}

/** josa('나이', '을', '를') → '나이를' */
export function josa(word: string, withFinal: string, withoutFinal: string): string {
  return word + (hasFinalConsonant(word) ? withFinal : withoutFinal);
}

/** '(으)로'는 ㄹ 받침에서도 '로'를 쓴다. */
export function josaRo(word: string): string {
  const last = word.trim().slice(-1);
  const code = last.charCodeAt(0);
  const isRieul = code >= 0xac00 && code <= 0xd7a3 && (code - 0xac00) % 28 === 8;
  return word + (hasFinalConsonant(word) && !isRieul ? '으로' : '로');
}
