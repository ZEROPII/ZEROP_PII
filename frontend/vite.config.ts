import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  // http 모드에서 VITE_API_BASE_URL=/api 로 두면 개발 서버가 백엔드(python -m api_server)로 넘긴다 (CORS 불필요).
  // /eval 은 데모 서버가 내보내는 평가 지표 대시보드(eval_demo/)
  server: { port: 5173, proxy: { '/api': 'http://127.0.0.1:8000', '/eval': 'http://127.0.0.1:8000' } },
});
