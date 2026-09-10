import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { VirtualizedTimeline } from "./VirtualizedTimeline.tsx";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("VirtualizedTimeline", () => {
  it("hydrates only the initial history and entries approaching the scroll viewport", async () => {
    let callback: IntersectionObserverCallback | null = null;
    let options: IntersectionObserverInit | undefined;
    const observed: Element[] = [];
    vi.stubGlobal("IntersectionObserver", class {
      constructor(nextCallback: IntersectionObserverCallback, nextOptions?: IntersectionObserverInit) {
        callback = nextCallback;
        options = nextOptions;
      }

      observe(element: Element) {
        observed.push(element);
      }

      disconnect() {}
    });

    const items = Array.from({ length: 5 }, (_, index) => ({
      key: `item-${index + 1}`,
      label: `Message ${index + 1}`,
    }));
    const { container } = render(
      <div className="agent-chat__timeline">
        <VirtualizedTimeline
          items={items}
          getKey={(item) => item.key}
          renderItem={(item) => <span>{item.label}</span>}
          initialVisibleCount={2}
        />
      </div>,
    );

    expect(screen.getByText("Message 1")).toBeTruthy();
    expect(screen.getByText("Message 2")).toBeTruthy();
    expect(screen.queryByText("Message 3")).toBeNull();
    expect(options?.root).toBe(container.querySelector(".agent-chat__timeline"));
    expect(options?.rootMargin).toBe("800px");

    const third = observed.find((element) => element.getAttribute("data-timeline-key") === "item-3");
    expect(third).toBeTruthy();
    await act(async () => {
      callback?.([{
        isIntersecting: true,
        target: third!,
      } as IntersectionObserverEntry], {} as IntersectionObserver);
    });

    await waitFor(() => expect(screen.getByText("Message 3")).toBeTruthy());
    expect(third?.getAttribute("data-timeline-hydrated")).toBe("true");
  });

  it("renders all history when IntersectionObserver is unavailable", async () => {
    vi.stubGlobal("IntersectionObserver", undefined);
    const items = Array.from({ length: 10 }, (_, index) => ({
      key: `item-${index + 1}`,
      label: `Message ${index + 1}`,
    }));

    render(
      <VirtualizedTimeline
        items={items}
        getKey={(item) => item.key}
        renderItem={(item) => <span>{item.label}</span>}
        initialVisibleCount={2}
      />,
    );

    await waitFor(() => expect(screen.getByText("Message 10")).toBeTruthy());
  });
});
