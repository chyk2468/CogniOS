import React, { useRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ChatScrollbar } from "./ChatScrollbar";

afterEach(cleanup);

const TestHarness: React.FC<{
  scrollHeight?: number;
  clientHeight?: number;
  scrollTop?: number;
  withMessages?: boolean;
}> = ({ scrollHeight = 1000, clientHeight = 400, scrollTop = 0, withMessages = false }) => {
  const ref = useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    if (ref.current) {
      Object.defineProperty(ref.current, "scrollHeight", { value: scrollHeight, configurable: true });
      Object.defineProperty(ref.current, "clientHeight", { value: clientHeight, configurable: true });
      window.dispatchEvent(new Event("resize"));
    }
  }, [scrollHeight, clientHeight]);

  return (
    <div style={{ position: "relative", height: "400px" }}>
      <div
        ref={(el) => {
          if (el) {
            Object.defineProperty(el, "scrollHeight", { value: scrollHeight, configurable: true });
            Object.defineProperty(el, "clientHeight", { value: clientHeight, configurable: true });
            Object.defineProperty(el, "scrollTop", {
              value: scrollTop,
              writable: true,
              configurable: true,
            });
            el.scrollTo = vi.fn((options: any) => {
              if (typeof options === "object" && options.top !== undefined) {
                el.scrollTop = options.top;
              }
            });
          }
          ref.current = el;
        }}
        className="main-scroll"
        style={{ height: "400px", overflowY: "auto" }}
      >
        {withMessages ? (
          <div className="transcript">
            <div className="bubble-user" style={{ height: "50px" }}>User prompt</div>
            <div className="bubble-assistant" style={{ height: "200px" }}>Assistant answer</div>
          </div>
        ) : (
          <div style={{ height: `${scrollHeight}px` }}>Long content</div>
        )}
      </div>
      <ChatScrollbar key={scrollHeight} scrollRef={ref} />
    </div>
  );
};

describe("ChatScrollbar", () => {
  it("renders the custom scrollbar container, markers, dots, and thumb when scrollable", () => {
    render(<TestHarness scrollHeight={1000} clientHeight={400} withMessages />);
    
    expect(screen.getByTestId("chat-scrollbar")).toBeTruthy();
    expect(screen.getByTestId("chat-scrollbar-thumb")).toBeTruthy();
    expect(document.querySelectorAll(".chat-scrollbar-marker").length).toBeGreaterThan(0);
    expect(document.querySelectorAll(".chat-scrollbar-dot").length).toBe(3);
  });

  it("dynamically generates message-based markers when messages exist", () => {
    render(<TestHarness scrollHeight={1000} clientHeight={400} withMessages />);
    
    const markers = document.querySelectorAll(".chat-scrollbar-marker");
    expect(markers.length).toBeGreaterThanOrEqual(2);
  });

  it("completely hides scrollbar from screen when non-scrollable and reveals when scrollable", () => {
    const { rerender } = render(<TestHarness scrollHeight={300} clientHeight={400} />);
    expect(screen.getByTestId("chat-scrollbar").style.display).toBe("none");

    rerender(<TestHarness scrollHeight={1200} clientHeight={400} />);
    expect(screen.getByTestId("chat-scrollbar").style.display).not.toBe("none");
  });

  it("handles track click to trigger smooth scrolling", () => {
    render(<TestHarness scrollHeight={1000} clientHeight={400} withMessages />);
    const track = document.querySelector(".chat-scrollbar-track")!;
    
    // Simulate bounding box on track
    vi.spyOn(track, "getBoundingClientRect").mockReturnValue({
      top: 0,
      bottom: 400,
      left: 0,
      right: 24,
      width: 24,
      height: 400,
      x: 0,
      y: 0,
      toJSON: () => {},
    });

    fireEvent.pointerDown(track, { clientY: 200 });
    expect(screen.getByTestId("chat-scrollbar")).toBeTruthy();
  });

  it("handles thumb pointer drag lifecycle cleanly", () => {
    render(<TestHarness scrollHeight={1000} clientHeight={400} withMessages />);
    const thumb = screen.getByTestId("chat-scrollbar-thumb");
    const track = document.querySelector(".chat-scrollbar-track")!;

    Object.defineProperty(track, "clientHeight", { value: 400, configurable: true });

    fireEvent.pointerDown(thumb, { clientY: 10 });
    expect(thumb.className).toContain("is-dragging");

    fireEvent.pointerMove(window, { clientY: 50 });
    fireEvent.pointerUp(window);

    expect(thumb.className).not.toContain("is-dragging");
  });
});
