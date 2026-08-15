import { useRef, useEffect, ReactNode } from "react";
import { Icon, type IconName } from "../Icon";
import { useWindowResizable } from "./useWindowResizable";
import { useWindowDraggable } from "./useWindowDraggable";

export interface FloatingWindowProps {
  id?: string;
  title: ReactNode;
  icon?: IconName;
  onClose: () => void;
  children: ReactNode;
  headerExtra?: ReactNode;
  storageKey?: string;
  enableDock?: boolean;
}

export function FloatingWindow({
  id,
  title,
  icon = "gear",
  onClose,
  children,
  headerExtra,
  storageKey,
  enableDock = true,
}: FloatingWindowProps) {
  const modalRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const headerRef = useRef<HTMLDivElement>(null);

  // Close on ESC key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  useWindowResizable({
    modalRef,
    contentRef,
    storageKey,
    isLocked: () => !!modalRef.current?.classList.contains("modal-right-docked"),
  });

  useWindowDraggable({
    modalRef,
    contentRef,
    headerRef,
    enableDock,
  });

  return (
    <div
      ref={modalRef}
      id={id}
      className="fixed inset-0 z-50 flex items-center justify-center pointer-events-none"
    >
      {/* Optional fallback overlay backdrop if desired, but dragging usually implies free floating */}
      <div
        ref={contentRef}
        className="floating-window w-[720px] max-w-[92vw] h-[85vh] flex flex-col rounded-lg border border-border bg-panel text-fg shadow-2xl overflow-hidden pointer-events-auto"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Draggable Modal Header */}
        <div
          ref={headerRef}
          className="modal-header px-4 py-3 bg-bg border-b border-border flex items-center justify-between shrink-0 cursor-move select-none"
        >
          <div className="flex items-center gap-2 text-[14px] font-semibold text-fg">
            {typeof icon === "string" && <Icon name={icon} size={16} className="text-accent" />}
            <span>{title}</span>
            <span className="text-[11px] text-muted font-normal ml-1">(drag header to move)</span>
          </div>

          <div className="flex items-center gap-2">
            {headerExtra}
            <button
              onClick={onClose}
              className="w-7 h-7 rounded-md grid place-items-center text-[13px] text-muted hover:bg-danger hover:text-white transition-colors"
              title="Close (Esc)"
              aria-label="Close"
            >
              ✕
            </button>
          </div>
        </div>

        {/* Modal Body */}
        <div className="floating-window-body flex-1 min-h-0 flex overflow-hidden bg-panel">{children}</div>
      </div>
    </div>
  );
}
