import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { RightRail } from "./RightRail";

function stubFetch(routes: { match: string; method?: string; json: any }[]) {
  const fn = vi.fn(async (url: string, init?: RequestInit) => {
    const method = (init?.method || "GET").toUpperCase();
    for (const r of routes) {
      if (url.includes(r.match) && (!r.method || r.method === method)) {
        return { ok: true, json: async () => r.json } as Response;
      }
    }
    return { ok: true, json: async () => ({}) } as Response;
  });
  vi.stubGlobal("fetch", fn);
}

const mockArtifacts = {
  artifacts: [
    { path: "analysis.md", name: "analysis.md", kind: "markdown", size: 1024, modified_at: 1700000000 },
    { path: "chart.png", name: "chart.png", kind: "image", size: 2048, modified_at: 1700000001 },
  ],
};

const mockConnections = {
  connected: [{ connector: "slack", enabled: true }],
  recommended: [],
};

describe("RightRail top icon tabs", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("renders permanent top icon tabs for Progress, Artifacts, and Access", async () => {
    stubFetch([
      { match: "/v1/sessions/s-1/artifacts", json: mockArtifacts },
      { match: "/v1/sessions/s-1/connections", json: mockConnections },
      { match: "/v1/connectors", json: { connectors: [] } },
      { match: "/v1/sessions/s-1/roots", json: { roots: [] } },
    ]);

    render(
      <RightRail
        active={true}
        sessionId="s-1"
        refreshKey={0}
        toolNames={[]}
        todo={[{ content: "Search codebase", status: "in_progress" }]}
        running={true}
        showArtifacts={true}
      />
    );

    const progressTab = screen.getByTestId("rail-tab-progress");
    const artifactsTab = screen.getByTestId("rail-tab-artifacts");
    const accessTab = screen.getByTestId("rail-tab-access");

    expect(progressTab).toBeTruthy();
    expect(artifactsTab).toBeTruthy();
    expect(accessTab).toBeTruthy();

    // Default active tab is progress
    expect(progressTab.getAttribute("aria-selected")).toBe("true");
    expect(screen.getByText("Search codebase")).toBeTruthy();

    // Artifacts tab shows badge count
    await waitFor(() => {
      expect(artifactsTab.textContent).toContain("2");
    });
  });

  it("switches to Artifacts tab when clicked and displays file list", async () => {
    stubFetch([
      { match: "/v1/sessions/s-1/artifacts", json: mockArtifacts },
      { match: "/v1/sessions/s-1/connections", json: mockConnections },
      { match: "/v1/connectors", json: { connectors: [] } },
      { match: "/v1/sessions/s-1/roots", json: { roots: [] } },
    ]);

    render(
      <RightRail
        active={true}
        sessionId="s-1"
        refreshKey={0}
        toolNames={[]}
        todo={[]}
        running={false}
        showArtifacts={true}
      />
    );

    const artifactsTab = screen.getByTestId("rail-tab-artifacts");
    expect(artifactsTab).toBeTruthy();

    fireEvent.click(artifactsTab);

    expect(screen.getByTestId("rail-tab-artifacts").getAttribute("aria-selected")).toBe("true");
    expect(screen.getByTestId("rail-tab-progress").getAttribute("aria-selected")).toBe("false");

    await waitFor(() => {
      expect(screen.getByText("analysis.md")).toBeTruthy();
      expect(screen.getByText("chart.png")).toBeTruthy();
    });
  });

  it("switches to Access tab when clicked or via openAccessKey", async () => {
    stubFetch([
      { match: "/v1/sessions/s-1/artifacts", json: { artifacts: [] } },
      { match: "/v1/sessions/s-1/connections", json: mockConnections },
      { match: "/v1/connectors", json: { connectors: [] } },
      { match: "/v1/sessions/s-1/roots", json: { roots: [] } },
    ]);

    const { rerender } = render(
      <RightRail
        active={true}
        sessionId="s-1"
        refreshKey={0}
        toolNames={[]}
        todo={[]}
        running={false}
        openAccessKey={0}
      />
    );

    fireEvent.click(screen.getByTestId("rail-tab-access"));
    expect(screen.getByTestId("rail-tab-access").getAttribute("aria-selected")).toBe("true");

    // Switching back to progress
    fireEvent.click(screen.getByTestId("rail-tab-progress"));
    expect(screen.getByTestId("rail-tab-progress").getAttribute("aria-selected")).toBe("true");

    // Rerender with deep link key triggers Access tab
    rerender(
      <RightRail
        active={true}
        sessionId="s-1"
        refreshKey={0}
        toolNames={[]}
        todo={[]}
        running={false}
        openAccessKey={1}
      />
    );

    expect(screen.getByTestId("rail-tab-access").getAttribute("aria-selected")).toBe("true");
  });

  it("renders specific tool executions with humanized names instead of a generic count", () => {
    stubFetch([
      { match: "/v1/sessions/s-1/artifacts", json: { artifacts: [] } },
      { match: "/v1/sessions/s-1/connections", json: mockConnections },
      { match: "/v1/connectors", json: { connectors: [] } },
      { match: "/v1/sessions/s-1/roots", json: { roots: [] } },
    ]);

    render(
      <RightRail
        active={true}
        sessionId="s-1"
        refreshKey={0}
        tools={[
          { kind: "tool", id: "1", name: "read_file", args: { path: "timetable.txt" }, status: "done" },
          { kind: "tool", id: "2", name: "web_search", args: { query: "Machine Vision Lab" }, status: "done" },
          { kind: "tool", id: "3", name: "run_shell", args: { command: "python selectionsort.py" }, status: "…" },
        ]}
        todo={[]}
        running={true}
      />
    );

    expect(screen.getByText("Tools Used (3)")).toBeTruthy();
    expect(screen.getByText("timetable.txt")).toBeTruthy();
    expect(screen.getByText("“Machine Vision Lab”")).toBeTruthy();
    expect(screen.getByText("python selectionsort.py")).toBeTruthy();
  });
});
