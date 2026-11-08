import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
// 글꼴은 앱 안에 넣는다: 인터넷이 막힌 병원 내부망 · 데스크톱 앱에서도 같은 글꼴로 보이고, 글꼴 CDN에 요청을 보내지 않는다 (ADR-0039)
import 'wanted-sans/fonts/webfonts/variable/split/WantedSansVariable.css';
import '@fontsource/geist-mono/400.css';
import '@fontsource/geist-mono/500.css';
import './index.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
