import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AppLayout } from './components/layout/AppLayout';
import { ToastProvider } from './components/layout/Toast';
import { AuditPage } from './pages/AuditPage';
import { CaseFinderPage } from './pages/CaseFinderPage';
import { HistoryPage } from './pages/HistoryPage';
import { MonitorPage } from './pages/MonitorPage';
import { PolicyPage } from './pages/PolicyPage';
import { ReportPage } from './pages/ReportPage';
import { WorkspaceProvider } from './state/WorkspaceContext';

export default function App() {
  return (
    <WorkspaceProvider>
      <ToastProvider>
        <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <Routes>
            <Route element={<AppLayout />}>
              <Route index element={<CaseFinderPage />} />
              <Route path="history" element={<HistoryPage />} />
              <Route path="policy" element={<PolicyPage />} />
              <Route path="monitor" element={<MonitorPage />} />
              <Route path="report" element={<ReportPage />} />
              <Route path="audit" element={<AuditPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </ToastProvider>
    </WorkspaceProvider>
  );
}
