import { useEffect } from "react";

const EDGE = 7; // px proximity to a border that arms a resize grip
const MIN_W = 320; // smallest a window may be dragged to
const MIN_H = 200;
const INTERACTIVE = 'button, input, select, textarea, a, [contenteditable=""], [contenteditable="true"]';

interface Edges {
  l: boolean;
  r: boolean;
  t: boolean;
  b: boolean;
  rect: DOMRect;
}

export interface UseWindowResizableOptions {
  modalRef: React.RefObject<HTMLElement>;
  contentRef: React.RefObject<HTMLElement>;
  mobileSkip?: number;
  isLocked?: () => boolean;
  minWidth?: number;
  minHeight?: number;
  storageKey?: string | null;
  onResizeEnd?: (rect: DOMRect) => void;
}

export function useWindowResizable({
  modalRef,
  contentRef,
  mobileSkip = 768,
  isLocked = () => false,
  minWidth = MIN_W,
  minHeight = MIN_H,
  storageKey = null,
  onResizeEnd = undefined,
}: UseWindowResizableOptions) {
  useEffect(() => {
    const content = contentRef.current;
    if (!content) return;

    const _skip = () => (mobileSkip > 0 && window.innerWidth <= mobileSkip) || isLocked();

    function edgesAt(cx: number, cy: number): Edges {
      const r = content!.getBoundingClientRect();
      const within = cy >= r.top - EDGE && cy <= r.bottom + EDGE && cx >= r.left - EDGE && cx <= r.right + EDGE;
      if (!within) return { l: false, r: false, t: false, b: false, rect: r };
      const onY = cy >= r.top - EDGE && cy <= r.bottom + EDGE;
      const onX = cx >= r.left - EDGE && cx <= r.right + EDGE;
      return {
        l: Math.abs(cx - r.left) <= EDGE && onY,
        r: Math.abs(cx - r.right) <= EDGE && onY,
        t: Math.abs(cy - r.top) <= EDGE && onX,
        b: Math.abs(cy - r.bottom) <= EDGE && onX,
        rect: r,
      };
    }

    function cursorFor(e: Edges): string {
      if ((e.l && e.t) || (e.r && e.b)) return "nwse-resize";
      if ((e.r && e.t) || (e.l && e.b)) return "nesw-resize";
      if (e.l || e.r) return "ew-resize";
      if (e.t || e.b) return "ns-resize";
      return "";
    }

    let hoverCursor = false;
    function clearHoverCursor() {
      if (hoverCursor) {
        content!.style.cursor = "";
        hoverCursor = false;
      }
    }

    function onHover(ev: MouseEvent) {
      if (resizing) return;
      if (_skip()) {
        clearHoverCursor();
        return;
      }
      if (ev.target && (ev.target as HTMLElement).closest && (ev.target as HTMLElement).closest(INTERACTIVE)) {
        clearHoverCursor();
        return;
      }
      const c = cursorFor(edgesAt(ev.clientX, ev.clientY));
      if (c) {
        content!.style.cursor = c;
        hoverCursor = true;
      } else clearHoverCursor();
    }

    let resizing = false;
    let active: Edges | null = null;
    let startRect: { left: number; top: number; width: number; height: number } | null = null;
    let startX = 0;
    let startY = 0;

    function begin(cx: number, cy: number, edges: Edges) {
      resizing = true;
      active = edges;
      content!.style.animation = "none";
      content!.classList.add("window-resizing");
      const r = content!.getBoundingClientRect();
      startRect = { left: r.left, top: r.top, width: r.width, height: r.height };
      startX = cx;
      startY = cy;

      content!.style.position = "fixed";
      content!.style.margin = "0";
      content!.style.transform = "none";
      content!.style.left = r.left + "px";
      content!.style.top = r.top + "px";
      content!.style.width = r.width + "px";
      content!.style.height = r.height + "px";
      content!.style.maxWidth = "none";
      content!.style.maxHeight = "none";
      document.body.classList.add("window-resizing-active");
      document.body.style.cursor = cursorFor(edges);
    }

    function move(cx: number, cy: number) {
      if (!resizing || !active || !startRect) return;
      const dx = cx - startX;
      const dy = cy - startY;
      let { left, top, width, height } = startRect;
      const vw = window.innerWidth;
      const vh = window.innerHeight;

      if (active.r) width = startRect.width + dx;
      if (active.b) height = startRect.height + dy;
      if (active.l) {
        width = startRect.width - dx;
        left = startRect.left + dx;
      }
      if (active.t) {
        height = startRect.height - dy;
        top = startRect.top + dy;
      }

      if (width < minWidth) {
        if (active.l) left = startRect.left + (startRect.width - minWidth);
        width = minWidth;
      }
      if (height < minHeight) {
        if (active.t) top = startRect.top + (startRect.height - minHeight);
        height = minHeight;
      }

      if (active.l && left < 0) {
        width += left;
        left = 0;
      }
      if (active.t && top < 0) {
        height += top;
        top = 0;
      }
      if (left + width > vw) width = Math.max(minWidth, vw - left);
      if (top + height > vh) height = Math.max(minHeight, vh - top);

      content!.style.left = left + "px";
      content!.style.top = top + "px";
      content!.style.width = width + "px";
      content!.style.height = height + "px";
    }

    function end() {
      if (!resizing) return;
      resizing = false;
      content!.classList.remove("window-resizing");
      document.body.classList.remove("window-resizing-active");
      document.body.style.cursor = "";
      clearHoverCursor();
      const r = content!.getBoundingClientRect();
      if (storageKey) {
        try {
          localStorage.setItem(storageKey, JSON.stringify({ w: Math.round(r.width), h: Math.round(r.height) }));
        } catch (_) {}
      }
      if (onResizeEnd) {
        try {
          onResizeEnd(r);
        } catch (_) {}
      }
    }

    function armFrom(target: EventTarget | null, cx: number, cy: number) {
      if (_skip()) return false;
      if (target && (target as HTMLElement).closest && (target as HTMLElement).closest(INTERACTIVE)) return false;
      const edges = edgesAt(cx, cy);
      if (!(edges.l || edges.r || edges.t || edges.b)) return false;
      begin(cx, cy, edges);
      return true;
    }

    const onMouseDown = (ev: MouseEvent) => {
      if (ev.button !== 0) return;
      if (!armFrom(ev.target, ev.clientX, ev.clientY)) return;
      ev.preventDefault();
      ev.stopPropagation();
      const mu = () => {
        end();
        document.removeEventListener("mousemove", mm);
        document.removeEventListener("mouseup", mu);
      };
      const mm = (e: MouseEvent) => {
        if (e.buttons === 0) {
          mu();
          return;
        }
        move(e.clientX, e.clientY);
      };
      document.addEventListener("mousemove", mm);
      document.addEventListener("mouseup", mu);
    };

    content.addEventListener("mousedown", onMouseDown, true);
    content.addEventListener("mousemove", onHover);
    content.addEventListener("mouseleave", clearHoverCursor);

    const onTouchStart = (ev: TouchEvent) => {
      const t = ev.touches[0];
      if (!t) return;
      if (!armFrom(ev.target, t.clientX, t.clientY)) return;
      ev.preventDefault();
      ev.stopPropagation();
      const tm = (e: TouchEvent) => {
        const tt = e.touches[0];
        if (tt) move(tt.clientX, tt.clientY);
      };
      const te = () => {
        end();
        document.removeEventListener("touchmove", tm);
        document.removeEventListener("touchend", te);
        document.removeEventListener("touchcancel", te);
      };
      document.addEventListener("touchmove", tm, { passive: false });
      document.addEventListener("touchend", te);
      document.addEventListener("touchcancel", te);
    };

    content.addEventListener("touchstart", onTouchStart, true);

    if (storageKey) {
      requestAnimationFrame(() => {
        if (_skip() || !content.isConnected) return;
        try {
          const saved = JSON.parse(localStorage.getItem(storageKey) || "null");
          if (saved && saved.w && saved.h) {
            const w = Math.max(minWidth, Math.min(saved.w, window.innerWidth));
            const h = Math.max(minHeight, Math.min(saved.h, window.innerHeight));
            content.style.width = w + "px";
            content.style.height = h + "px";
            content.style.maxWidth = "none";
            content.style.maxHeight = "none";
          }
        } catch (_) {}
      });
    }

    return () => {
      content.removeEventListener("mousedown", onMouseDown, true);
      content.removeEventListener("mousemove", onHover);
      content.removeEventListener("mouseleave", clearHoverCursor);
      content.removeEventListener("touchstart", onTouchStart, true);
    };
  }, [contentRef, modalRef, mobileSkip, isLocked, minWidth, minHeight, storageKey, onResizeEnd]);
}
