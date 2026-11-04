import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AppLayout } from './components/layout/AppLayout';
import { ToastProvider } from './components/layout/Toast';
import { AuditPage } from './pages/AuditPage';
import { ClinicalAssistPage } from './pages/ClinicalAssistPage';
import { GuidePage } from './pages/GuidePage';
import { HistoryPage } from './pages/HistoryPage';
import { MonitorPage } from './pages/MonitorPage';
import { PolicyPage } from './pages/PolicyPage';
import { ReportPage } from './pages/ReportPage';
import { TerminologyPage } from './pages/TerminologyPage';
import { WatchPage } from './pages/WatchPage';
import { WorkspaceProvider } from './state/WorkspaceContext';

export default function App() {
  return (
    <WorkspaceProvider>
      <ToastProvider>
        <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <Routes>
            <Route element={<AppLayout />}>
              {/* 의료진 (EMR 진료 지원 AI) */}
              <Route index element={<ClinicalAssistPage />} />
              <Route path="history" element={<HistoryPage />} />
              <Route path="guide" element={<GuidePage />} />
              {/* 보안 담당자 (MediCloak 관제) */}
              <Route path="monitor" element={<MonitorPage />} />
              <Route path="watch" element={<WatchPage />} />
              <Route path="report" element={<ReportPage />} />
              <Route path="audit" element={<AuditPage />} />
              <Route path="terms" element={<TerminologyPage />} />
              <Route path="policy" element={<PolicyPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </ToastProvider>
    </WorkspaceProvider>
  );
}
