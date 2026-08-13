import { useEffect, useRef } from "react";

const SNAP_PX = 60; // cursor distance from L/R edge to trigger dock hint
const UNSNAP_PX = 80; // distance to drag away from docked edge to undock
const MIN_CHAT_WIDTH = 380;
const MIN_EDGE_DOCK_WIDTH = 320;
const MOVE_THRESHOLD = 4;

export interface UseWindowDraggableOptions {
  modalRef: React.RefObject<HTMLElement>;
  contentRef: React.RefObject<HTMLElement>;
  headerRef: React.RefObject<HTMLElement>;
  mobileSkip?: number;
  enableDock?: boolean;
  skipSelector?: string;
  onDragStart?: (state: { rect: DOMRect; cx: number; cy: number }) => void;
  onDragEnd?: (state: { rect: DOMRect }) => void;
}

export function useWindowDraggable({
  modalRef,
  contentRef,
  headerRef,
  mobileSkip = 768,
  enableDock = true,
  skipSelector = 'button, input, select, textarea, a',
  onDragStart,
  onDragEnd,
}: UseWindowDraggableOptions) {
  const draggingRef = useRef(false);
  const movedRef = useRef(false);
  const startPosRef = useRef({ x: 0, y: 0, left: 0, top: 0 });
  const snapHintRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const modal = modalRef.current;
    const content = contentRef.current;
    const header = headerRef.current;
    if (!content || !header || !modal) return;

    header.style.cursor = "move";
    header.style.userSelect = "none";

    const _showSnapHint = (on: boolean, side: "right" | "left" = "right") => {
      const cls = side === "left" ? "modal-snap-hint-left" : "modal-snap-hint-right";
      if (!on) {
        if (snapHintRef.current) {
          snapHintRef.current.remove();
          snapHintRef.current = null;
        }
        return;
      }
      if (snapHintRef.current) return;
      
      const hint = document.createElement("div");
      hint.className = `modal-snap-hint ${cls}`;
      const w = Math.min(640, Math.max(420, Math.round(window.innerWidth * 0.38)));
      const edge = side === "left" ? "left:0" : "right:0";
      const borderSide = side === "left" ? "border-right" : "border-left";
      hint.style.cssText = `position:fixed;${edge};top:0;bottom:0;width:${w}px;background:color-mix(in srgb, var(--accent-primary, #60a5fa) 12%, transparent);${borderSide}:2px dashed color-mix(in srgb, var(--accent-primary, #60a5fa) 60%, transparent);z-index:9998;pointer-events:none;transition:opacity 0.12s;`;
      document.body.appendChild(hint);
      snapHintRef.current = hint;
    };

    const _clampRightDockWidth = (width: number) => {
      const min = window.innerWidth < 900 ? 280 : MIN_EDGE_DOCK_WIDTH;
      const maxByChat = window.innerWidth - MIN_CHAT_WIDTH;
      const max = Math.min(Math.round(window.innerWidth * 0.82), maxByChat);
      const floor = Math.min(min, Math.max(220, max));
      return Math.min(max, Math.max(floor, Math.round(width)));
    };

    const _resolveRightDockWidth = () => {
      const fallback = Math.min(640, Math.max(420, Math.round(window.innerWidth * 0.38)));
      let w = fallback;
      try {
        const stored = localStorage.getItem(`cognios-edge-dock-width:right:${modal.id}`);
        if (stored) w = parseFloat(stored) || fallback;
      } catch (_) {}
      return _clampRightDockWidth(w);
    };

    const _applyRightDock = () => {
      const w = _resolveRightDockWidth();
      modal.classList.add("modal-right-docked");
      
      // Save snapshot if not already saved
      if (!(content as any)._preDockSnapshot) {
        const r = content.getBoundingClientRect();
        (content as any)._preDockSnapshot = {
          rect: { left: r.left, top: r.top, width: r.width, height: r.height },
          style: {
            position: content.style.position,
            left: content.style.left,
            top: content.style.top,
            right: content.style.right,
            bottom: content.style.bottom,
            width: content.style.width,
            maxWidth: content.style.maxWidth,
            height: content.style.height,
            maxHeight: content.style.maxHeight,
            borderRadius: content.style.borderRadius,
            transform: content.style.transform,
            margin: content.style.margin,
          },
        };
      }

      content.style.position = "fixed";
      content.style.top = "0";
      content.style.bottom = "0";
      content.style.height = "100vh";
      content.style.maxHeight = "100vh";
      content.style.borderRadius = "0";
      content.style.transform = "none";
      content.style.margin = "0";
      content.style.left = "auto";
      content.style.right = "0";
      content.style.width = w + "px";
      content.style.maxWidth = w + "px";

      document.body.classList.add("right-dock-active");
      document.documentElement.style.setProperty("--right-dock-w", w + "px");
    };

    const _clearRightDock = (cx?: number, cy?: number) => {
      if (!modal.classList.contains("modal-right-docked")) return;
      modal.classList.remove("modal-right-docked");
      document.body.classList.remove("right-dock-active");
      document.documentElement.style.removeProperty("--right-dock-w");
      
      const snap = (content as any)._preDockSnapshot;
      const r = snap?.rect;
      const sty = snap?.style || {};
      
      content.style.position = sty.position || "fixed";
      content.style.right = sty.right || "";
      content.style.bottom = sty.bottom || "";
      content.style.width = sty.width || (r?.width ? r.width + "px" : "");
      content.style.maxWidth = sty.maxWidth || "";
      content.style.height = sty.height || (r?.height ? r.height + "px" : "");
      content.style.maxHeight = sty.maxHeight || "";
      content.style.borderRadius = sty.borderRadius || "";
      content.style.transform = sty.transform || "";
      content.style.margin = sty.margin || "";
      
      const refW = r?.width || content.offsetWidth || 720;
      const refH = r?.height || content.offsetHeight || (window.innerHeight * 0.7);
      
      const targetLeft = typeof cx === "number" ? Math.max(8, cx - refW / 2) : (sty.left || (r ? r.left + "px" : Math.max(8, (window.innerWidth - refW) / 2) + "px"));
      const targetTop = typeof cy === "number" ? Math.max(8, cy - 20) : (sty.top || (r ? r.top + "px" : Math.max(8, (window.innerHeight - refH) / 3) + "px"));
      
      content.style.left = typeof targetLeft === "number" ? targetLeft + "px" : targetLeft;
      content.style.top = typeof targetTop === "number" ? targetTop + "px" : targetTop;
      
      delete (content as any)._preDockSnapshot;
    };

    let _hoveringSnapRight = false;
    const _distFromRightEdge = (cx: number) => window.innerWidth - cx;

    const dockController = {
      onMove(cx: number, cy: number) {
        if (modal.classList.contains("modal-right-docked")) {
          if (_distFromRightEdge(cx) > UNSNAP_PX) {
            _clearRightDock(cx, cy);
            return true;
          }
          return false;
        }
        const nearEdge = _distFromRightEdge(cx) <= SNAP_PX;
        if (nearEdge !== _hoveringSnapRight) {
          _hoveringSnapRight = nearEdge;
          _showSnapHint(nearEdge, "right");
        }
        return false;
      },
      hovering: () => _hoveringSnapRight,
      commit() {
        _showSnapHint(false, "right");
        _hoveringSnapRight = false;
        _applyRightDock();
      },
      release() {
        _showSnapHint(false, "right");
        _hoveringSnapRight = false;
      }
    };

    const _startDrag = (cx: number, cy: number) => {
      draggingRef.current = true;
      modal.classList.add("modal-dragging");
      try {
        content.getAnimations().filter(a => a.playState !== "finished").forEach(a => a.cancel());
      } catch (_) {}
      
      const rect = content.getBoundingClientRect();
      if (onDragStart) {
        try { onDragStart({ rect, cx, cy }); } catch (_) {}
      }
      
      startPosRef.current = { x: cx, y: cy, left: rect.left, top: rect.top };
      
      // If we are docked, do not override position yet until un-snapped
      if (!modal.classList.contains("modal-right-docked")) {
        content.style.position = "fixed";
        content.style.left = rect.left + "px";
        content.style.top = rect.top + "px";
        content.style.transform = "none";
        content.style.margin = "0";
      }
    };

    const _onMove = (cx: number, cy: number) => {
      if (!draggingRef.current) return;
      
      if (enableDock && modal.classList.contains("modal-right-docked")) {
        if (dockController.onMove(cx, cy)) {
          const r = content.getBoundingClientRect();
          startPosRef.current = { x: cx, y: cy, left: r.left, top: r.top };
        }
        return;
      }

      if (Math.abs(cx - startPosRef.current.x) > MOVE_THRESHOLD || Math.abs(cy - startPosRef.current.y) > MOVE_THRESHOLD) {
        movedRef.current = true;
      }
      
      content.style.left = (startPosRef.current.left + cx - startPosRef.current.x) + "px";
      content.style.top = (startPosRef.current.top + cy - startPosRef.current.y) + "px";
      
      if (enableDock) dockController.onMove(cx, cy);
    };

    const _onEnd = () => {
      if (!draggingRef.current) return;
      draggingRef.current = false;
      modal.classList.remove("modal-dragging");
      
      if (enableDock && dockController.hovering()) {
        dockController.commit();
        return;
      }
      
      if (enableDock) dockController.release();
      
      if (onDragEnd) {
        const r = content.getBoundingClientRect();
        try { onDragEnd({ rect: r }); } catch (_) {}
      }
    };

    const handleMouseDown = (e: MouseEvent) => {
      if (mobileSkip > 0 && window.innerWidth <= mobileSkip) return;
      if (skipSelector && (e.target as HTMLElement).closest(skipSelector)) return;
      e.preventDefault();
      movedRef.current = false;
      _startDrag(e.clientX, e.clientY);
      
      const onMove = (ev: MouseEvent) => _onMove(ev.clientX, ev.clientY);
      const onUp = () => {
        _onEnd();
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        
        if (movedRef.current) {
          const swallow = (clickEv: Event) => {
            clickEv.stopPropagation();
            clickEv.preventDefault();
          };
          header.addEventListener("click", swallow, { capture: true, once: true });
          setTimeout(() => header.removeEventListener("click", swallow, { capture: true }), 50);
        }
      };
      
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    };

    header.addEventListener("mousedown", handleMouseDown);

    // Cleanup watcher for docked modal removal
    const onModalGone = () => {
      if (modal.classList.contains("modal-right-docked")) {
        _clearRightDock();
      }
    };

    let obs: MutationObserver | null = null;
    if (typeof MutationObserver !== 'undefined') {
      const _isGone = () => !modal.isConnected || modal.classList.contains("hidden") || modal.style.display === "none";
      obs = new MutationObserver(() => { if (_isGone()) onModalGone(); });
      obs.observe(modal, { attributes: true, attributeFilter: ["class", "style"] });
    }

    return () => {
      header.removeEventListener("mousedown", handleMouseDown);
      if (obs) obs.disconnect();
      onModalGone(); // ensure cleanup of body classes if component unmounts
    };
  }, [modalRef, contentRef, headerRef, mobileSkip, enableDock, skipSelector, onDragStart, onDragEnd]);
}
