/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Noto Sans KR"', 'Inter', '"Malgun Gothic"', 'system-ui', 'sans-serif'],
      },
      colors: {
        navy: { 800: '#1b2a4a', 900: '#13203b', 950: '#0d1730' },
      },
      boxShadow: {
        card: '0 1px 2px rgba(16, 24, 40, 0.05), 0 1px 3px rgba(16, 24, 40, 0.04)',
      },
    },
  },
  plugins: [],
};
