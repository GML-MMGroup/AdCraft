export type ParticleMotionFrame = {
  time: number;
  intro: number;
  hover: [number, number];
  moving: boolean;
};

/** One clock for both viewports. No geometry uploads or React updates per frame. */
export function createParticleMotion(
  canvas: HTMLCanvasElement,
  render: (frame: ParticleMotionFrame) => void,
  options: { interactionElement?: Element; shapeIndex?: number; hoverOnly?: boolean } = {},
) {
  const interactionElement = options.interactionElement ?? canvas;
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const pointer = matchMedia("(hover: hover) and (pointer: fine)");
  const frame: ParticleMotionFrame = { time: 0, intro: 0, hover: [0, 0], moving: true };
  let paused = false;
  let visible = true;
  let disposed = false;
  let target = -1;
  let raf = 0;
  let last = 0;
  const hasHover = () => target >= 0 || frame.hover.some(value => value > 0.001);
  const canRun = () => !disposed && !paused && !reduced.matches && visible && !document.hidden
    && (!options.hoverOnly || hasHover());
  const draw = () => {
    frame.moving = !paused && !reduced.matches && (!options.hoverOnly || hasHover());
    if (options.hoverOnly) frame.intro = 1;
    if (!frame.moving) {
      frame.intro = 1;
      frame.hover = [0, 0];
    }
    render(frame);
  };
  const tick = (now: number) => {
    raf = 0;
    if (!canRun()) {
      // Media-query state may update before its change event is delivered.
      // Paint the static pose before stopping the clock in that case.
      if (!disposed && !document.hidden && visible) draw();
      return;
    }
    const dt = last ? Math.min((now - last) / 1000, 0.05) : 0;
    last = now;
    frame.time += dt;
    frame.intro = Math.min(1, frame.intro + dt / 0.75);
    const response = 1 - Math.exp(-dt / (target < 0 ? 0.035 : 0.075));
    frame.hover = frame.hover.map((value, index) =>
      value + ((target === index ? 1 : 0) - value) * response) as [number, number];
    draw();
    raf = requestAnimationFrame(tick);
  };
  const sync = () => {
    cancelAnimationFrame(raf);
    raf = 0;
    last = 0;
    if (disposed) return;
    draw();
    if (canRun()) raf = requestAnimationFrame(tick);
  };
  const move = (event: Event) => {
    if (!pointer.matches || reduced.matches || paused) return;
    const bounds = canvas.getBoundingClientRect();
    target = options.shapeIndex ?? ((event as PointerEvent).clientX < bounds.left + bounds.width / 2 ? 0 : 1);
    if (!raf) sync();
  };
  const leave = () => { target = -1; };
  const changePointer = () => { leave(); sync(); };
  const observer = new IntersectionObserver(entries => {
    visible = entries[0]?.isIntersecting ?? false;
    if (!visible) leave();
    sync();
  });
  observer.observe(canvas);
  interactionElement.addEventListener("pointermove", move);
  interactionElement.addEventListener("pointerenter", move);
  interactionElement.addEventListener("pointerleave", leave);
  document.addEventListener("visibilitychange", sync);
  reduced.addEventListener("change", sync);
  pointer.addEventListener("change", changePointer);
  sync();
  return {
    redraw: draw,
    setPaused(value: boolean) { paused = value; leave(); sync(); },
    dispose() {
      disposed = true;
      cancelAnimationFrame(raf);
      observer.disconnect();
      interactionElement.removeEventListener("pointermove", move);
      interactionElement.removeEventListener("pointerenter", move);
      interactionElement.removeEventListener("pointerleave", leave);
      document.removeEventListener("visibilitychange", sync);
      reduced.removeEventListener("change", sync);
      pointer.removeEventListener("change", changePointer);
    },
  };
}
