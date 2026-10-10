import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";

const STORAGE_KEY = "citebase-active-conversation";

export function useConversationState() {
  const location = useLocation();
  const [conversationId, setConversationId] = useState(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) || null;
    } catch {
      return null;
    }
  });

  useEffect(() => {
    if (!conversationId) {
      try {
        localStorage.removeItem(STORAGE_KEY);
      } catch {
        // ignore storage failures
      }
      return;
    }
    try {
      localStorage.setItem(STORAGE_KEY, conversationId);
    } catch {
      // ignore storage failures
    }
  }, [conversationId]);

  useEffect(() => {
    if (!location.pathname.startsWith("/chat")) return;
    try {
      const persisted = localStorage.getItem(STORAGE_KEY);
      if (persisted && persisted !== conversationId) {
        setConversationId(persisted);
      }
    } catch {
      // ignore storage failures
    }
  }, [conversationId, location.pathname]);

  const clearConversationId = useCallback(() => {
    setConversationId(null);
  }, []);

  return useMemo(
    () => ({ conversationId, setConversationId, clearConversationId }),
    [conversationId, clearConversationId],
  );
}
