import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AppLayout } from './components/layout/AppLayout';
import { ToastProvider } from './components/layout/Toast';
import { AuditPage } from './pages/AuditPage';
import { ClinicalAssistPage } from './pages/ClinicalAssistPage';
import { EmrAccessPage } from './pages/EmrAccessPage';
import { EmrPage } from './pages/EmrPage';
import { GuidePage } from './pages/GuidePage';
import { HistoryPage } from './pages/HistoryPage';
import { MonitorPage } from './pages/MonitorPage';
import { PolicyPage } from './pages/PolicyPage';
import { ReportPage } from './pages/ReportPage';
import { TerminologyPage } from './pages/TerminologyPage';
import { WatchPage } from './pages/WatchPage';
import { AuthProvider } from './state/AuthContext';

/** 의료진 화면의 대화 상태(WorkspaceProvider)는 AppLayout이 의료진 틀 안에서만 만든다 (보안 담당자 계정은 그 API를 쓸 수 없다). */
export default function App() {
  return (
    <AuthProvider>
      <ToastProvider>
        <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <Routes>
            <Route element={<AppLayout />}>
              {/* 의료진 (EMR 진료 지원 AI) */}
              <Route index element={<ClinicalAssistPage />} />
              <Route path="emr" element={<EmrPage />} />
              <Route path="emr/:fhirId" element={<EmrPage />} />
              <Route path="history" element={<HistoryPage />} />
              <Route path="guide" element={<GuidePage />} />
              {/* 보안 담당자 (MediCloak 관제) */}
              <Route path="monitor" element={<MonitorPage />} />
              <Route path="watch" element={<WatchPage />} />
              <Route path="report" element={<ReportPage />} />
              <Route path="emr-access" element={<EmrAccessPage />} />
              <Route path="audit" element={<AuditPage />} />
              <Route path="terms" element={<TerminologyPage />} />
              <Route path="policy" element={<PolicyPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </ToastProvider>
    </AuthProvider>
  );
}
