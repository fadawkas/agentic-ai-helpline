import { useEffect, useRef, type ReactNode } from "react";

type DialogProps = {
  titleId: string;
  children: ReactNode;
  onClose: () => void;
};

export function Dialog({ titleId, children, onClose }: DialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const dialog = dialogRef.current;
    const focusable = dialog?.querySelector<HTMLElement>("input:not([disabled])")
      ?? dialog?.querySelector<HTMLElement>("select:not([disabled]), button:not([disabled]), textarea:not([disabled]), [href], summary");
    focusable?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !dialog) return;
      const items = [...dialog.querySelectorAll<HTMLElement>("input:not([disabled]), select:not([disabled]), button:not([disabled]), textarea:not([disabled]), [href], summary")].filter((item) => item.offsetParent !== null);
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      previousFocus?.focus();
    };
  }, []);

  return <div className="fixed inset-0 z-50 grid place-items-center overflow-y-auto bg-forest-950/55 p-3 sm:p-6" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={titleId} className="my-auto max-h-[calc(100dvh-1.5rem)] w-full max-w-xl overflow-y-auto rounded-2xl border border-stone-200 bg-paper-50 p-5 shadow-2xl sm:p-7">
      {children}
    </div>
  </div>;
}
