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
        toast: { DEFAULT: v('toast'), text: v('toast-text') },
        scrim: v('scrim'),
      },
      borderRadius: { cell: '6px', control: '10px', panel: '16px', overlay: '20px' },
      boxShadow: { overlay: v('shadow-overlay') },
      fontSize: { '2xs': ['11px', '16px'] },
      transitionTimingFunction: { zp: 'cubic-bezier(.2,.8,.2,1)' },
    },
  },
  plugins: [],
};
