import React, { useEffect, useRef, useState, useCallback } from "react";

interface ChatScrollbarProps {
  scrollRef: React.RefObject<HTMLDivElement>;
  items?: any[];
  streaming?: string | null;
}

interface ContentMarker {
  id: string;
  topPercent: number; // 0 to 100
  width: number; // in px (e.g. 7 to 18)
}

const MIN_THUMB_HEIGHT = 28;
const HIDE_TIMEOUT_MS = 1200;
const FALLBACK_PATTERN = [7, 13, 7, 15, 7, 14, 7, 13, 7, 15, 7, 14, 7, 18, 7, 14, 7];

export const ChatScrollbar: React.FC<ChatScrollbarProps> = ({ scrollRef, items, streaming }) => {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const trackRef = useRef<HTMLDivElement | null>(null);
  const thumbRef = useRef<HTMLDivElement | null>(null);
  const [isScrollable, setIsScrollable] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [isActive, setIsActive] = useState(false);
  const [markers, setMarkers] = useState<ContentMarker[]>([]);
  const hideTimerRef = useRef<number | null>(null);

  // Cached layout metrics to avoid layout reads during high-frequency drags
  const metricsRef = useRef({
    scrollHeight: 0,
    clientHeight: 0,
    scrollTop: 0,
    trackHeight: 0,
    thumbHeight: MIN_THUMB_HEIGHT,
    thumbTop: 0,
    isScrollable: false,
  });

  const showScrollbarTemporarily = useCallback(() => {
    setIsActive(true);
    if (hideTimerRef.current !== null) {
      window.clearTimeout(hideTimerRef.current);
    }
    hideTimerRef.current = window.setTimeout(() => {
      setIsActive(false);
      hideTimerRef.current = null;
    }, HIDE_TIMEOUT_MS);
  }, []);

  const updateMetrics = useCallback(() => {
    const el = scrollRef.current;
    const track = trackRef.current;
    if (!el) return;

    const sH = el.scrollHeight;
    const cH = el.clientHeight;
    const sT = el.scrollTop;
    const tH = (track ? track.clientHeight : 0) || cH || 400;

    const scrollable = sH > cH + 10;
    let thumbH = MIN_THUMB_HEIGHT;
    let thumbT = 0;

    if (scrollable && sH > 0 && tH > 0) {
      const ratio = cH / sH;
      thumbH = Math.max(MIN_THUMB_HEIGHT, Math.min(tH - 8, Math.round(tH * ratio)));
      const maxScroll = sH - cH;
      const maxTravel = Math.max(0, tH - thumbH);
      thumbT = maxScroll > 0 ? Math.round((sT / maxScroll) * maxTravel) : 0;
      thumbT = Math.max(0, Math.min(maxTravel, thumbT));
    }

    metricsRef.current = {
      scrollHeight: sH,
      clientHeight: cH,
      scrollTop: sT,
      trackHeight: tH,
      thumbHeight: thumbH,
      thumbTop: thumbT,
      isScrollable: scrollable,
    };

    if (scrollable !== isScrollable) {
      setIsScrollable(scrollable);
    }

    if (thumbRef.current) {
      thumbRef.current.style.height = `${thumbH}px`;
      thumbRef.current.style.transform = `translateY(${thumbT}px)`;
      thumbRef.current.style.opacity = scrollable ? "1" : "0";
    }

    // ── Calculate Content Position Markers from Real Message Nodes ──
    if (!scrollable) {
      setMarkers([]);
      return;
    }

    const containerRect = el.getBoundingClientRect();
    const messageElements = el.querySelectorAll<HTMLElement>(
      ".bubble-user, .bubble-assistant, .turn-narr, .turn-ask, .notice, .approval-inline, .hero",
    );

    if (messageElements.length > 0 && sH > 0) {
      const newMarkers: ContentMarker[] = [];
      messageElements.forEach((msg, idx) => {
        const msgRect = msg.getBoundingClientRect();
        const relativeTop = sT + (msgRect.top - containerRect.top);
        const topPercent = Math.max(0, Math.min(96, (relativeTop / sH) * 100));

        let width = 8;
        if (msg.classList.contains("bubble-user") || msg.closest(".bubble-user")) {
          width = 7;
        } else if (msg.classList.contains("bubble-assistant") || msg.closest(".bubble-assistant")) {
          width = 14;
        } else if (msg.classList.contains("turn-narr") || msg.classList.contains("turn-ask")) {
          width = 11;
        } else if (msg.classList.contains("hero")) {
          width = 16;
        } else {
          width = 9;
        }

        newMarkers.push({
          id: `msg-${idx}`,
          topPercent,
          width,
        });

        if (msg.offsetHeight > 220) {
          const midRelativeTop = relativeTop + msg.offsetHeight * 0.5;
          const midPercent = Math.max(0, Math.min(96, (midRelativeTop / sH) * 100));
          newMarkers.push({
            id: `msg-${idx}-sub`,
            topPercent: midPercent,
            width: 7,
          });
        }
      });

      newMarkers.sort((a, b) => a.topPercent - b.topPercent);
      setMarkers(newMarkers);
    } else {
      // Fallback rhythmic pattern for scrollable long content without standard bubble classes
      const pitchCount = Math.max(8, Math.floor((tH > 0 ? tH - 40 : 300) / 16));
      const fallbackMarkers: ContentMarker[] = Array.from({ length: pitchCount }, (_, i) => ({
        id: `fb-${i}`,
        topPercent: (i / Math.max(1, pitchCount)) * 95,
        width: FALLBACK_PATTERN[i % FALLBACK_PATTERN.length],
      }));
      setMarkers(fallbackMarkers);
    }
  }, [scrollRef, isScrollable]);

  useEffect(() => {
    const el = scrollRef.current;
    const track = trackRef.current;
    if (!el) return;

    let rafId: number | null = null;
    const scheduleUpdate = () => {
      if (rafId !== null) return;
      rafId = requestAnimationFrame(() => {
        rafId = null;
        updateMetrics();
      });
    };

    updateMetrics();

    // Fast scroll handler: direct transform update + show scrollbar temporarily
    const onScroll = () => {
      showScrollbarTemporarily();

      const sH = el.scrollHeight;
      const cH = el.clientHeight;
      const sT = el.scrollTop;
      const tH = metricsRef.current.trackHeight || (track ? track.clientHeight : 0) || cH || 400;
      const thumbH = metricsRef.current.thumbHeight;
      const maxScroll = sH - cH;
      const maxTravel = Math.max(0, tH - thumbH);

      if (maxScroll > 0 && maxTravel > 0) {
        const thumbT = Math.max(0, Math.min(maxTravel, Math.round((sT / maxScroll) * maxTravel)));
        metricsRef.current.scrollTop = sT;
        metricsRef.current.thumbTop = thumbT;
        if (thumbRef.current) {
          thumbRef.current.style.transform = `translateY(${thumbT}px)`;
        }
      } else {
        scheduleUpdate();
      }
    };

    el.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", scheduleUpdate);

    let ro: ResizeObserver | null = null;
    if (typeof ResizeObserver !== "undefined") {
      ro = new ResizeObserver(() => scheduleUpdate());
      ro.observe(el);
      if (track) ro.observe(track);
      if (el.firstElementChild) ro.observe(el.firstElementChild);
    }

    let mo: MutationObserver | null = null;
    if (typeof MutationObserver !== "undefined") {
      mo = new MutationObserver(() => scheduleUpdate());
      mo.observe(el, {
        childList: true,
        subtree: true,
        characterData: true,
        attributes: true,
      });
    }

    return () => {
      el.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", scheduleUpdate);
      if (rafId !== null) cancelAnimationFrame(rafId);
      if (hideTimerRef.current !== null) clearTimeout(hideTimerRef.current);
      ro?.disconnect();
      mo?.disconnect();
    };
  }, [scrollRef, updateMetrics, showScrollbarTemporarily, items, streaming]);

  // Thumb drag handling
  const handleThumbPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();

    const el = scrollRef.current;
    if (!el) return;

    const startY = e.clientY;
    const startScrollTop = el.scrollTop;
    const sH = el.scrollHeight;
    const cH = el.clientHeight;
    const tH = (trackRef.current ? trackRef.current.clientHeight : 0) || metricsRef.current.trackHeight || cH || 400;
    const thumbH = metricsRef.current.thumbHeight || MIN_THUMB_HEIGHT;
    const maxTravel = Math.max(1, tH - thumbH);
    const maxScroll = Math.max(1, sH - cH);

    setIsDragging(true);
    setIsActive(true);
    if (hideTimerRef.current !== null) clearTimeout(hideTimerRef.current);

    const onPointerMove = (moveEvent: Event | MouseEvent | PointerEvent) => {
      const clientY = (moveEvent as MouseEvent).clientY;
      const deltaY = clientY - startY;
      const scrollDelta = (deltaY / maxTravel) * maxScroll;
      const targetScroll = Math.max(0, Math.min(maxScroll, startScrollTop + scrollDelta));
      el.scrollTop = targetScroll;
    };

    const onPointerUp = () => {
      setIsDragging(false);
      showScrollbarTemporarily();
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
      window.removeEventListener("pointercancel", onPointerUp);
      window.removeEventListener("mousemove", onPointerMove);
      window.removeEventListener("mouseup", onPointerUp);
    };

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
    window.addEventListener("pointercancel", onPointerUp);
    window.addEventListener("mousemove", onPointerMove);
    window.addEventListener("mouseup", onPointerUp);
  };

  // Track click to jump
  const handleTrackPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.target === thumbRef.current) return;

    const el = scrollRef.current;
    const track = trackRef.current;
    if (!el || !track) return;

    const rect = track.getBoundingClientRect();
    const clickY = e.clientY - rect.top;
    const tH = track.clientHeight || el.clientHeight || 400;
    const thumbH = metricsRef.current.thumbHeight;
    const maxTravel = tH - thumbH;
    const maxScroll = el.scrollHeight - el.clientHeight;

    if (maxTravel <= 0 || maxScroll <= 0) return;

    const targetThumbTop = clickY - thumbH / 2;
    const ratio = Math.max(0, Math.min(1, targetThumbTop / maxTravel));
    const targetScroll = ratio * maxScroll;

    showScrollbarTemporarily();
    el.scrollTo({ top: targetScroll, behavior: "smooth" });
  };

  const handlePointerEnter = () => {
    if (isScrollable) {
      setIsActive(true);
      if (hideTimerRef.current !== null) clearTimeout(hideTimerRef.current);
    }
  };

  const handlePointerLeave = () => {
    if (!isDragging) {
      showScrollbarTemporarily();
    }
  };

  const visibleClass = isScrollable && (isActive || isDragging) ? " is-active" : "";

  return (
    <div
      ref={containerRef}
      className={`chat-scrollbar-container${visibleClass}${isDragging ? " is-dragging" : ""}${!isScrollable ? " is-hidden" : ""}`}
      onPointerEnter={handlePointerEnter}
      onPointerLeave={handlePointerLeave}
      data-testid="chat-scrollbar"
      style={!isScrollable ? { display: "none", opacity: 0, pointerEvents: "none" } : undefined}
    >
      <div
        ref={trackRef}
        className="chat-scrollbar-track"
        onPointerDown={handleTrackPointerDown}
        role="scrollbar"
        aria-controls="main-scroll"
        aria-valuenow={metricsRef.current.scrollTop}
        aria-valuemin={0}
        aria-valuemax={metricsRef.current.scrollHeight - metricsRef.current.clientHeight}
      >
        {/* Dynamic content-position indicator markers */}
        {markers.length > 0 && (
          <div className="chat-scrollbar-markers" aria-hidden="true">
            {markers.map((m) => (
              <span
                key={m.id}
                className="chat-scrollbar-marker"
                style={{
                  top: `${m.topPercent}%`,
                  width: `${m.width}px`,
                }}
              />
            ))}
            {/* Subtle terminating dots matching reference */}
            <div className="chat-scrollbar-dots">
              <span className="chat-scrollbar-dot" />
              <span className="chat-scrollbar-dot" />
              <span className="chat-scrollbar-dot" />
            </div>
          </div>
        )}

        {/* Minimalist vertical rounded pill scroll thumb */}
        <div
          ref={thumbRef}
          className={`chat-scrollbar-thumb${isDragging ? " is-dragging" : ""}`}
          onPointerDown={handleThumbPointerDown}
          data-testid="chat-scrollbar-thumb"
          style={{
            height: `${MIN_THUMB_HEIGHT}px`,
            transform: "translateY(0px)",
            opacity: isScrollable ? 1 : 0,
          }}
        />
      </div>
    </div>
  );
};
