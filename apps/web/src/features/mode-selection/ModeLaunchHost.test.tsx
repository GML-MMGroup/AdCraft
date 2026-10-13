import { useEffect } from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { ModeLaunchHost } from "./ModeLaunchHost";
import { useModeLaunch } from "./ModeLaunchContext";
vi.mock("../../components/Layout", () => ({ Layout: ({children}: {children: React.ReactNode}) => <>{children}</> }));
vi.mock("../../pages/ModeSelectionPage", () => ({ ModeSelectionPage: () => {
  const launch = useModeLaunch()!;
  return <button data-testid="overlay" data-revealing={String(launch.revealing)} onClick={() => launch.begin("brand", "p", false)}>Choose</button>;
} }));
let mounts = 0;
function Canvas() {
  const launch = useModeLaunch()!;
  useEffect(() => { mounts++; }, []);
  return <button onClick={launch.ready}>Canvas ready</button>;
}
afterEach(cleanup);
it("keeps the cover until readiness, then removes it without remounting the canvas", async () => {
  mounts = 0;
  render(<MemoryRouter initialEntries={["/projects/new"]}><Routes><Route element={<ModeLaunchHost />}>
    <Route path="/projects/new" element={null}/><Route path="/workflow/:id" element={<Canvas/>}/>
  </Route></Routes></MemoryRouter>);
  fireEvent.click(await screen.findByText("Choose"));
  expect(screen.getByTestId("overlay").getAttribute("data-revealing")).toBe("false");
  expect(screen.getByText("Canvas ready").closest('[inert]')).not.toBeNull();
  fireEvent.click(screen.getByText("Canvas ready"));
  await act(() => new Promise(resolve => setTimeout(resolve, 80)));
  expect(screen.getByTestId("overlay").getAttribute("data-revealing")).toBe("true");
  await act(() => new Promise(resolve => setTimeout(resolve, 540)));
  expect(screen.queryByTestId("overlay")).toBeNull();
  expect(mounts).toBe(1);
  expect(screen.getByText("Canvas ready").closest('[inert]')).toBeNull();
});
