import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./context/AuthContext";
import { ToastProvider } from "./components/ui";
import { AppLayout, ProtectedRoute } from "./components/Chrome";
import { AuthPage } from "./components/AuthPanel";
import AuthCallbackPage from "./pages/AuthCallback";
import PrivacyPage from "./pages/Privacy";
import LandingPage from "./pages/Landing";
import { AcceptInvitePage } from "./pages/Auth";
import DocumentsPage from "./pages/Documents";
import ChatPage from "./pages/Chat";
import TeamPage from "./pages/Team";
import InsightsPage from "./pages/Insights";
import { QuickAsk } from "./components/QuickAsk";
import { ServerWake } from "./components/ServerWake";

function AppShell({ children }) {
  return (
    <AppLayout>
      {children}
      <QuickAsk />
    </AppLayout>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <ToastProvider>
          <ServerWake />
          <Routes>
            <Route path="/" element={<LandingPage />} />
            <Route path="/login" element={<AuthPage mode="signin" />} />
            <Route path="/signup" element={<AuthPage mode="signup" />} />
            <Route path="/auth/callback" element={<AuthCallbackPage />} />
            <Route path="/privacy" element={<PrivacyPage />} />
            <Route path="/invite" element={<AcceptInvitePage />} />

            <Route
              path="/documents"
              element={
                <ProtectedRoute>
                  <AppShell>
                    <DocumentsPage />
                  </AppShell>
                </ProtectedRoute>
              }
            />
            <Route
              path="/chat"
              element={
                <ProtectedRoute>
                  <AppShell>
                    <ChatPage />
                  </AppShell>
                </ProtectedRoute>
              }
            />

            <Route
              path="/team"
              element={
                <ProtectedRoute>
                  <AppShell>
                    <TeamPage />
                  </AppShell>
                </ProtectedRoute>
              }
            />

            <Route
              path="/insights"
              element={
                <ProtectedRoute>
                  <AppShell>
                    <InsightsPage />
                  </AppShell>
                </ProtectedRoute>
              }
            />

            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </ToastProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}
