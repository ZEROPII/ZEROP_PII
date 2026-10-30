import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  // http 모드에서 VITE_API_BASE_URL=/api 로 두면 개발 서버가 백엔드(python -m api_server)로 넘긴다 (CORS 불필요).
  server: { port: 5173, proxy: { '/api': 'http://127.0.0.1:8000' } },
});
