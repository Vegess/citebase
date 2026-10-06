import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./context/AuthContext";
import { ToastProvider } from "./components/ui";
import { Navbar, ProtectedRoute } from "./components/Chrome";
import LandingPage from "./pages/Landing";
import { AcceptInvitePage, LoginPage, SignupPage } from "./pages/Auth";
import DocumentsPage from "./pages/Documents";
import ChatPage from "./pages/Chat";
import TeamPage from "./pages/Team";

function AppShell({ children }) {
  return (
    <>
      <Navbar />
      {children}
    </>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <ToastProvider>
          <Routes>
            <Route path="/" element={<LandingPage />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/signup" element={<SignupPage />} />
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

            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </ToastProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}
