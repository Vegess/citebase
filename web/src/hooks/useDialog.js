import { useEffect, useRef } from "react";

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Modal behaviour for a dialog element: focus moves inside when it opens, Tab
 * stays inside, Escape closes it, and focus returns to where it was.
 */
export function useDialog(onClose, active = true) {
  const ref = useRef(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    if (!active) return undefined;
    const previous = document.activeElement;
    const node = ref.current;
    const items = () => Array.from(node?.querySelectorAll(FOCUSABLE) ?? []).filter((el) => el.offsetParent !== null);
    (items().find((el) => el.dataset.autofocus !== undefined) || items()[0] || node)?.focus();

    const onKey = (e) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        closeRef.current?.();
      } else if (e.key === "Tab") {
        const list = items();
        if (list.length === 0) return;
        const first = list[0];
        const last = list[list.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      if (previous && typeof previous.focus === "function") previous.focus();
    };
  }, [active]);

  return ref;
}
