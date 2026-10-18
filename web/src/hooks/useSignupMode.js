import { useEffect, useState } from "react";
import * as api from "../lib/api";

/** "open" or "waitlist" (SIGNUP_MODE on the server). "open" until it loads. */
export function useSignupMode() {
  const [mode, setMode] = useState("open");
  useEffect(() => {
    let live = true;
    api.getSignupMode().then((m) => live && setMode(m));
    return () => {
      live = false;
    };
  }, []);
  return mode;
}
