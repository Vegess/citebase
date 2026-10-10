import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./context/AuthContext";
import { ToastProvider } from "./components/ui";
import { AppLayout, GuestOnly, ProtectedRoute } from "./components/Chrome";
import { AuthPage } from "./components/AuthPanel";
import AuthCallbackPage from "./pages/AuthCallback";
import PrivacyPage from "./pages/Privacy";
import HomePage from "./pages/Home";
import SettingsPage from "./pages/Settings";
import { ForgotPasswordPage, ResetPasswordPage } from "./pages/PasswordReset";
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
            <Route path="/login" element={<GuestOnly><AuthPage mode="signin" /></GuestOnly>} />
            <Route path="/signup" element={<GuestOnly><AuthPage mode="signup" /></GuestOnly>} />
            <Route path="/forgot-password" element={<ForgotPasswordPage />} />
            <Route path="/reset-password" element={<ResetPasswordPage />} />
            <Route path="/auth/callback" element={<AuthCallbackPage />} />
            <Route path="/privacy" element={<PrivacyPage />} />
            <Route path="/invite" element={<AcceptInvitePage />} />

            <Route
              path="/home"
              element={
                <ProtectedRoute>
                  <AppShell>
                    <HomePage />
                  </AppShell>
                </ProtectedRoute>
              }
            />
            <Route
              path="/settings"
              element={
                <ProtectedRoute>
                  <AppShell>
                    <SettingsPage />
                  </AppShell>
                </ProtectedRoute>
              }
            />
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
