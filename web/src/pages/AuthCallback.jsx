import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { Wordmark } from "../components/Chrome";

const ERRORS = {
  cancelled: "Sign-in was cancelled.",
  expired: "That sign-in link expired. Please try again.",
  state_mismatch: "We couldn't verify that sign-in attempt. Please start again from this site.",
  no_verified_email: "Your account needs a verified email address to sign in.",
  provider_error: "The sign-in provider didn't respond. Please try again.",
  provider_disabled: "That sign-in option isn't set up on this server.",
  use_password:
    "This email already has a Citebase password. Sign in with your email and password instead.",
  not_approved:
    "Citebase is invite-only right now and this email hasn't been approved yet. Request access and we'll email you when you're in.",
  account_removed: "This account was removed from its workspace. Ask an admin for a new invite.",
};

/** Google/GitHub send the browser here with #token=… (or #error=…). */
export default function AuthCallbackPage() {
  const { signInWithToken } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState("");
  const [notApproved, setNotApproved] = useState(false);
  const handled = useRef(false);

  useEffect(() => {
    if (handled.current) return;
    handled.current = true;
    const params = new URLSearchParams(window.location.hash.slice(1));
    // Remove the token from the address bar and browser history straight away.
    window.history.replaceState(null, "", window.location.pathname);
    const token = params.get("token");
    if (!token) {
      setNotApproved(params.get("error") === "not_approved");
      setError(ERRORS[params.get("error")] || "Sign-in didn't complete. Please try again.");
      return;
    }
    signInWithToken(token).then(() => navigate("/home", { replace: true }));
  }, [signInWithToken, navigate]);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-5 text-center">
      <Wordmark className="text-2xl" />
      {error ? (
        <>
          <p role="alert" className="mt-6 max-w-sm rounded-md bg-danger-soft px-4 py-3 text-sm text-danger">
            {error}
          </p>
          {notApproved ? (
            <Link to="/signup" className="mt-4 text-sm text-signal">
              Request access
            </Link>
          ) : (
            <Link to="/login" className="mt-4 text-sm text-signal">
              Back to sign in
            </Link>
          )}
        </>
      ) : (
        <p className="mt-6 text-sm text-muted">Signing you in…</p>
      )}
    </div>
  );
}
