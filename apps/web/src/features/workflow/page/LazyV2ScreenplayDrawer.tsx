import { lazy, Suspense, type MutableRefObject } from "react";
import { createPortal } from "react-dom";
import type { ScreenplayProductOption } from "../v2/screenplay/screenplayUiHelpers.ts";
import type { V2ScreenplayController } from "../v2/screenplay/useV2ScreenplayController.ts";

const V2ScreenplayDrawer = lazy(() => import("../v2/screenplay/V2ScreenplayDrawer.tsx")
  .then((module) => ({ default: module.V2ScreenplayDrawer })));

export function LazyV2ScreenplayDrawer({
  controller,
  productOptions,
  returnFocusRef,
}: {
  controller: V2ScreenplayController;
  productOptions: ScreenplayProductOption[];
  returnFocusRef: MutableRefObject<HTMLElement | null>;
}) {
  return createPortal(
    <Suspense fallback={<ScreenplayDrawerLoading />}>
      <V2ScreenplayDrawer controller={controller} productOptions={productOptions} returnFocusRef={returnFocusRef} />
    </Suspense>,
    document.body,
  );
}

function ScreenplayDrawerLoading() {
  return <div className="v2-screenplay-drawer-backdrop">
    <aside className="v2-screenplay-drawer" role="status" aria-live="polite">
      <p className="v2-screenplay-status">Loading screenplay editor...</p>
    </aside>
  </div>;
}
