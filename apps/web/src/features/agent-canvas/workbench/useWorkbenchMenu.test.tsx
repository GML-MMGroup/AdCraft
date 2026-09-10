import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { CanvasModelPicker } from "./CanvasModelPicker.tsx";

let triggerTop: number;
let menuHeight: number;
let triggerLeft: number;
let measuredVisibility: string[];
let resize: (() => void) | undefined;
const disconnect = vi.fn();
function rect(left: number, top: number, width: number, height: number): DOMRect {
  return { left, top, width, height, x: left, y: top, right: left + width, bottom: top + height, toJSON: () => ({}) };
}
beforeEach(() => {
  triggerTop = 820; menuHeight = 128.5; triggerLeft = 253; measuredVisibility = []; resize = undefined;
  disconnect.mockClear();
  vi.stubGlobal("innerWidth", 1280); vi.stubGlobal("innerHeight", 900);
  vi.stubGlobal("ResizeObserver", class {
    constructor(callback: () => void) { resize = callback; }
    observe() {}
    disconnect = disconnect;
  });
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    if (this.tagName === "SUMMARY") return rect(triggerLeft, triggerTop, 280, 32);
    if (this.classList.contains("agent-node-workbench__model-menu")) {
      measuredVisibility.push(this.style.visibility);
      return rect(0, 0, 360, menuHeight);
    }
    return rect(0, 0, 0, 0);
  });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
function mount() {
  const view = render(<CanvasModelPicker models={[]} loading={false} error={null} selectionMode="default"
    modelRef={null} modelSummary={null} disabled={false} onChange={vi.fn()} appearance="monochrome" />);
  fireEvent.click(screen.getByLabelText("Choose model"));
  return view;
}

it("measures a hidden mounted menu and displays its actual anchored height", () => {
  mount();
  expect(measuredVisibility[0]).toBe("hidden");
  const menu = screen.getByRole("listbox");
  expect(menu.style.top).toBe("686.5px");
  expect(menu.style.left).toBe("253px");
  expect(menu.style.visibility).toBe("visible");
});

it("places the actual short menu below when there is room", () => {
  triggerTop = 650;
  mount();
  expect(screen.getByRole("listbox").style.top).toBe("687px");
});

it("tracks menu and trigger size changes without flipping the chosen side", () => {
  mount();
  expect(resize).toBeDefined();
  menuHeight = 90;
  act(() => resize!());
  expect(screen.getByRole("listbox").style.top).toBe("725px");
  triggerTop = 600;
  act(() => resize!());
  expect(screen.getByRole("listbox").style.top).toBe("505px");
  menuHeight = 220;
  act(() => resize!());
  expect(screen.getByRole("listbox").style.top).toBe("375px");
});

it("ignores equal measurements instead of writing styles repeatedly", () => {
  mount();
  const menu = screen.getByRole("listbox");
  const mutations: MutationRecord[] = [];
  const observer = new MutationObserver((records) => mutations.push(...records));
  observer.observe(menu, { attributes: true });
  act(() => { for (let i = 0; i < 5; i++) resize?.(); });
  expect(observer.takeRecords()).toHaveLength(0);
  observer.disconnect();
});

it("reopens using new geometry and disconnects observers", () => {
  const view = mount();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(disconnect).toHaveBeenCalledOnce();
  menuHeight = 75;
  fireEvent.click(screen.getByLabelText("Choose model"));
  expect(screen.getByRole("listbox").style.top).toBe("740px");
  view.unmount();
  expect(disconnect).toHaveBeenCalledTimes(2);
});

it("constrains a short viewport and clamps the menu horizontally", () => {
  vi.stubGlobal("innerWidth", 330); vi.stubGlobal("innerHeight", 300);
  triggerTop = 150; triggerLeft = 290; menuHeight = 236;
  mount();
  const menu = screen.getByRole("listbox");
  expect(menu.style.left).toBe("12px");
  expect(menu.style.width).toBe("306px");
  expect(menu.style.maxHeight).toBe("133px");
  expect(menu.style.top).toBe("12px");
});

it("updates on scroll and cancels a scheduled update on close", () => {
  let frame: FrameRequestCallback | undefined;
  vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => { frame = callback; return 42; });
  const cancel = vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => {});
  mount();
  triggerTop = 700;
  fireEvent.scroll(window);
  act(() => frame!(0));
  expect(screen.getByRole("listbox").style.top).toBe("566.5px");
  fireEvent.scroll(window);
  act(() => resize!());
  fireEvent.keyDown(document, { key: "Escape" });
  expect(cancel).toHaveBeenCalledWith(42);
});

it("switches sides when the old side cannot fit a usable option", () => {
  mount();
  triggerTop = 18;
  act(() => resize!());
  const menu = screen.getByRole("listbox");
  expect(menu.style.top).toBe("55px");
  expect(menu.style.maxHeight).toBe("236px");
});
