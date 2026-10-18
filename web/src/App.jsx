import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./context/AuthContext";
import { ToastProvider } from "./components/ui";
import { AdminOnly, AppLayout, FullPageNote, GuestOnly, PlatformAdminOnly, ProtectedRoute } from "./components/Chrome";
import { AuthPage } from "./components/AuthPanel";
import LandingPage from "./pages/Landing";
import { QuickAsk } from "./components/QuickAsk";
import { ServerWake } from "./components/ServerWake";

// The landing page loads straight away; everything behind sign-in is fetched
// on first visit, so first-time visitors download much less JavaScript.
const AuthCallbackPage = lazy(() => import("./pages/AuthCallback"));
const PrivacyPage = lazy(() => import("./pages/Privacy"));
const HomePage = lazy(() => import("./pages/Home"));
const SettingsPage = lazy(() => import("./pages/Settings"));
const DocumentsPage = lazy(() => import("./pages/Documents"));
const DocumentDetailPage = lazy(() => import("./pages/DocumentDetail"));
const ChatPage = lazy(() => import("./pages/Chat"));
const TeamPage = lazy(() => import("./pages/Team"));
const InsightsPage = lazy(() => import("./pages/Insights"));
const ForgotPasswordPage = lazy(() => import("./pages/PasswordReset").then((m) => ({ default: m.ForgotPasswordPage })));
const VerifyEmailPage = lazy(() => import("./pages/PasswordReset").then((m) => ({ default: m.VerifyEmailPage })));
const ResetPasswordPage = lazy(() => import("./pages/PasswordReset").then((m) => ({ default: m.ResetPasswordPage })));
const AdminAccessPage = lazy(() => import("./pages/AdminAccess"));
const AcceptInvitePage = lazy(() => import("./pages/Auth").then((m) => ({ default: m.AcceptInvitePage })));

function InApp({ children }) {
  return (
    <ProtectedRoute>
      <AppLayout>
        <Suspense fallback={<div className="p-10 text-sm text-muted">Loading…</div>}>{children}</Suspense>
        <QuickAsk />
      </AppLayout>
    </ProtectedRoute>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <ToastProvider>
          <ServerWake />
          <Suspense fallback={<FullPageNote>Loading…</FullPageNote>}>
            <Routes>
              <Route path="/" element={<LandingPage />} />
              <Route path="/login" element={<GuestOnly><AuthPage mode="signin" /></GuestOnly>} />
              <Route path="/signup" element={<GuestOnly><AuthPage mode="signup" /></GuestOnly>} />
              <Route path="/forgot-password" element={<ForgotPasswordPage />} />
              <Route path="/reset-password" element={<ResetPasswordPage />} />
              <Route path="/verify-email" element={<VerifyEmailPage />} />
              <Route path="/auth/callback" element={<AuthCallbackPage />} />
              <Route path="/privacy" element={<PrivacyPage />} />
              <Route path="/invite" element={<AcceptInvitePage />} />

              <Route path="/home" element={<InApp><HomePage /></InApp>} />
              <Route path="/chat" element={<InApp><ChatPage /></InApp>} />
              <Route path="/documents" element={<InApp><DocumentsPage /></InApp>} />
              <Route path="/documents/:id" element={<InApp><DocumentDetailPage /></InApp>} />
              <Route path="/insights" element={<InApp><AdminOnly><InsightsPage /></AdminOnly></InApp>} />
              <Route path="/team" element={<InApp><AdminOnly><TeamPage /></AdminOnly></InApp>} />
              <Route path="/settings" element={<InApp><SettingsPage /></InApp>} />
              <Route path="/admin/access" element={<InApp><PlatformAdminOnly><AdminAccessPage /></PlatformAdminOnly></InApp>} />

              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
        </ToastProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}
