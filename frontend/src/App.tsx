import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AppLayout } from './components/layout/AppLayout';
import { CaseFinderPage } from './pages/CaseFinderPage';
import { HistoryPage } from './pages/HistoryPage';
import { PolicyPage } from './pages/PolicyPage';
import { WorkspaceProvider } from './state/WorkspaceContext';

export default function App() {
  return (
    <WorkspaceProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<AppLayout />}>
            <Route index element={<CaseFinderPage />} />
            <Route path="history" element={<HistoryPage />} />
            <Route path="policy" element={<PolicyPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </WorkspaceProvider>
  );
}
