import { Outlet } from 'react-router-dom';
import { apiMode } from '../../api';
import { Header } from './Header';

export function AppLayout() {
  return (
    <div className="flex h-dvh flex-col bg-slate-100 text-slate-800">
      <Header />
      {apiMode === 'mock' && (
        <p className="shrink-0 border-b border-amber-200 bg-amber-50 px-4 py-1 text-center text-[11px] text-amber-800">
          Mock 모드 — 백엔드 없이 가상 데이터로 동작합니다. 사례·k 값은 UI 확인용 예시이며 실험 결과가 아닙니다.
        </p>
      )}
      <main className="min-h-0 flex-1">
        <Outlet />
      </main>
    </div>
  );
}
