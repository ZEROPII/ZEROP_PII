/** @type {import('tailwindcss').Config} */
// Zero PII 디자인 토큰 (src/index.css의 CSS 변수). 라이트/다크는 변수 값만 바뀐다.
const v = (name) => `var(--zp-${name})`;

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Wanted Sans Variable"', '"Wanted Sans"', '"Pretendard Variable"', 'Pretendard', '-apple-system', 'BlinkMacSystemFont', '"Apple SD Gothic Neo"', '"Malgun Gothic"', 'system-ui', 'sans-serif'],
        mono: ['"Geist Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      colors: {
        page: v('page'),
        surface: v('surface'),
        'surface-2': v('surface-2'),
        line: v('line'),
        'line-input': v('line-input'),
        ink: { DEFAULT: v('text'), 2: v('text-2'), 3: v('text-3') },
        iris: { DEFAULT: v('iris'), text: v('iris-text'), tint: v('iris-tint'), on: v('on-iris') },
        focus: v('focus'),
        safe: { DEFAULT: v('safe'), text: v('safe-text'), tint: v('safe-tint') },
        caution: { DEFAULT: v('caution'), text: v('caution-text'), tint: v('caution-tint') },
        danger: { DEFAULT: v('danger'), text: v('danger-text'), tint: v('danger-tint') },
        series: { 1: v('series-1'), 2: v('series-2'), 3: v('series-3') },
        // 기록 종류 (진단 · 처방 · 시술 · 관리 · 내원만)와 환자 위험 등급 (1 위급 ~ 5 안정)
        kind: Object.fromEntries(['dx', 'rx', 'px', 'care', 'visit'].flatMap((k) => [[k, v(`kind-${k}`)], [`${k}-text`, v(`kind-${k}-text`)], [`${k}-tint`, v(`kind-${k}-tint`)], [`${k}-on`, v(`kind-${k}-on`)]])),
        tri: Object.fromEntries([1, 2, 3, 4, 5].flatMap((k) => [[`${k}`, v(`tri-${k}`)], [`${k}-text`, v(`tri-${k}-text`)], [`${k}-tint`, v(`tri-${k}-tint`)], [`${k}-on`, v(`tri-${k}-on`)]])),
        toast: { DEFAULT: v('toast'), text: v('toast-text') },
        scrim: v('scrim'),
        // 의료진 화면(EMR) 전용: 앱 머리줄, 환자 띠, 잠금 표시
        emr: {
          chrome: 'var(--emr-chrome)',
          'chrome-text': 'var(--emr-chrome-text)',
          'chrome-muted': 'var(--emr-chrome-muted)',
          'chrome-line': 'var(--emr-chrome-line)',
          'chrome-hover': 'var(--emr-chrome-hover)',
          banner: 'var(--emr-banner)',
          lock: 'var(--emr-lock)',
          'lock-tint': 'var(--emr-lock-tint)',
        },
      },
      borderRadius: { cell: '6px', control: '10px', panel: '16px', overlay: '20px' },
      boxShadow: { overlay: v('shadow-overlay') },
      fontSize: { '2xs': ['11px', '16px'] },
      transitionTimingFunction: { zp: 'cubic-bezier(.2,.8,.2,1)' },
    },
  },
  plugins: [],
};
