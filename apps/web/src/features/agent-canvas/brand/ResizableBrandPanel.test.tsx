import { brandPanelMaxWidth } from "./brandPanelResize";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ResizableBrandPanel } from "./ResizableBrandPanel";
beforeEach(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function(this: HTMLElement) {
    return {width:this.className === "agent-chat" ? 390 : 1440} as DOMRect;
  });
});
afterEach(() => {cleanup();vi.restoreAllMocks();vi.unstubAllGlobals();});
it("caps width while reserving canvas and chat space", () => {
  expect(brandPanelMaxWidth(1440,390)).toBe(520);
  expect(brandPanelMaxWidth(1100,390)).toBe(390);
  expect(brandPanelMaxWidth(1100,720)).toBe(260);
});
it("supports keyboard resizing and clamps both ends", () => {
  const {container} = render(<div><ResizableBrandPanel><aside>Brand content</aside></ResizableBrandPanel><div className="agent-chat"/></div>);
  const handle = screen.getByRole("separator", {name:"Resize brand decision panel"});
  fireEvent.keyDown(handle,{key:"ArrowRight"});
  expect(handle.getAttribute("aria-valuenow")).toBe("324");
  expect((container.firstChild as HTMLElement).style.getPropertyValue("--brand-panel-width")).toBe("324px");
  fireEvent.keyDown(handle,{key:"End"});expect(handle.getAttribute("aria-valuenow")).toBe("520");
  fireEvent.keyDown(handle,{key:"ArrowRight"});expect(handle.getAttribute("aria-valuenow")).toBe("520");
  fireEvent.keyDown(handle,{key:"Home"});fireEvent.keyDown(handle,{key:"ArrowLeft"});expect(handle.getAttribute("aria-valuenow")).toBe("260");
});
