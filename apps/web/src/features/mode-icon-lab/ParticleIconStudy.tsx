import { useEffect, useRef, useState } from "react";
import { createParticleGeometry, type ParticleShape } from "./particleGeometry";
import { vertexSource, fragmentSource } from "./particleShaders";
import { createParticleMotion, type ParticleMotionFrame } from "./particleMotion";
import { drawParticleFallback } from "./particleFallback";

export function ParticleIconStudy({ paused = false, shape, hoverOnly = false, accented = false, className = "particle-study__art" }: {
  paused?: boolean;
  shape?: ParticleShape;
  className?: string;
  hoverOnly?: boolean;
  accented?: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const fallbackRef = useRef<HTMLCanvasElement>(null);
  const motionRef = useRef<ReturnType<typeof createParticleMotion> | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  // Bumped when a lost context is restored so the effect rebuilds GPU resources.
  const [contextGeneration, setContextGeneration] = useState(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const gl = canvas.getContext("webgl", { alpha: true, antialias: false, premultipliedAlpha: false });
    if (!gl) { setUnavailable(true); return; }
    const restored = () => { setUnavailable(false); setContextGeneration(generation => generation + 1); };
    canvas.addEventListener("webglcontextrestored", restored);
    // Browsers cap live WebGL contexts (about 16 in Chrome) and only reclaim a
    // removed canvas on GC, so release it explicitly once it is truly unmounted.
    // The deferred check keeps StrictMode's remount of the same canvas working.
    const release = () => window.setTimeout(() => {
      if (!canvas.isConnected) gl.getExtension("WEBGL_lose_context")?.loseContext();
    });
    const shaders: WebGLShader[] = [];
    const buffers: WebGLBuffer[] = [];
    let program: WebGLProgram | null = null;
    let observer: ResizeObserver | undefined;
    const dispose = () => {
      observer?.disconnect();
      motionRef.current?.dispose();
      motionRef.current = null;
      buffers.forEach(buffer => gl.deleteBuffer(buffer));
      shaders.forEach(shader => gl.deleteShader(shader));
      if (program) gl.deleteProgram(program);
    };
    const lost = (event: Event) => { event.preventDefault(); motionRef.current?.dispose(); setUnavailable(true); };
    canvas.addEventListener("webglcontextlost", lost);
    const cleanup = () => {
      canvas.removeEventListener("webglcontextlost", lost);
      canvas.removeEventListener("webglcontextrestored", restored);
      dispose();
      release();
    };
    // A context lost elsewhere stays lost until the browser restores it.
    if (gl.isContextLost()) { setUnavailable(true); return cleanup; }
    try {
      const compile = (type: number, source: string) => {
        const shader = gl.createShader(type);
        if (!shader) throw new Error("Shader allocation failed");
        shaders.push(shader);
        gl.shaderSource(shader, source);
        gl.compileShader(shader);
        if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error("Shader compilation failed");
        return shader;
      };
      program = gl.createProgram();
      if (!program) throw new Error("Program allocation failed");
      gl.attachShader(program, compile(gl.VERTEX_SHADER, vertexSource));
      gl.attachShader(program, compile(gl.FRAGMENT_SHADER, fragmentSource));
      gl.linkProgram(program);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error("Program linking failed");
      gl.useProgram(program);
      const position = gl.getAttribLocation(program, "a_position");
      const size = gl.getAttribLocation(program, "a_size");
      const color = gl.getAttribLocation(program, "a_color");
      const flow = gl.getAttribLocation(program, "a_flow");
      const phase = gl.getAttribLocation(program, "a_phase");
      const uniforms = Object.fromEntries(["time", "intro", "hover", "shape", "motion", "accent"].map(name => [name, gl.getUniformLocation(program!, `u_${name}`)]));
      const scale = gl.getUniformLocation(program, "u_scale");
      const dprLocation = gl.getUniformLocation(program, "u_dpr");
      const shapes: ParticleShape[] = shape ? [shape] : ["butterfly", "infinity"];
      const counts = shapes.map(shape => {
        const buffer = gl.createBuffer();
        if (!buffer) throw new Error("Buffer allocation failed");
        buffers.push(buffer);
        const data = createParticleGeometry(shape);
        gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
        gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
        return data.length / 10;
      });
      const draw = (frame: ParticleMotionFrame) => {
        if (gl.isContextLost()) return;
        const bounds = canvas.getBoundingClientRect();
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        const nextWidth = Math.round(bounds.width * dpr);
        const nextHeight = Math.round(bounds.height * dpr);
        if (canvas.width !== nextWidth || canvas.height !== nextHeight) {
          canvas.width = nextWidth;
          canvas.height = nextHeight;
        }
        gl.clearColor(0, 0, 0, 0);
        gl.clear(gl.COLOR_BUFFER_BIT);
        gl.enable(gl.BLEND);
        gl.blendFuncSeparate(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA, gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
        gl.useProgram(program);
        gl.uniform1f(dprLocation, dpr);
        gl.uniform1f(uniforms.time, frame.time);
        gl.uniform1f(uniforms.accent, accented ? 1 : 0);
        gl.uniform1f(uniforms.intro, frame.intro);
        gl.uniform1f(uniforms.motion, frame.moving ? (hoverOnly ? Math.max(...frame.hover) : 1) : 0);
        const width = Math.floor(canvas.width / shapes.length);
        const extent = Math.min(width, canvas.height) * (shape ? 0.96 : 0.86);
        gl.uniform2f(scale, extent / width, extent / canvas.height);
        buffers.forEach((buffer, index) => {
          const shapeIndex = shapes[index] === "butterfly" ? 0 : 1;
          gl.uniform1f(uniforms.shape, shapeIndex);
          gl.uniform1f(uniforms.hover, frame.hover[shapeIndex]);
          gl.viewport(index * width, 0, width, canvas.height);
          gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
          gl.enableVertexAttribArray(position);
          gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 40, 0);
          gl.enableVertexAttribArray(size);
          gl.vertexAttribPointer(size, 1, gl.FLOAT, false, 40, 8);
          gl.enableVertexAttribArray(color);
          gl.vertexAttribPointer(color, 4, gl.FLOAT, false, 40, 12);
          gl.enableVertexAttribArray(phase);
          gl.vertexAttribPointer(phase, 1, gl.FLOAT, false, 40, 28);
          gl.enableVertexAttribArray(flow);
          gl.vertexAttribPointer(flow, 2, gl.FLOAT, false, 40, 32);
          gl.drawArrays(gl.POINTS, 0, counts[index]);
          [position, size, color, phase, flow].forEach(attribute => gl.disableVertexAttribArray(attribute));
        });
      };
      canvas.dataset.infinityParticles = String(counts[shapes.indexOf("infinity")] ?? 0);
      motionRef.current = createParticleMotion(canvas, draw, {
        interactionElement: canvas.closest("[data-particle-hover]") ?? canvas,
        shapeIndex: shape ? (shape === "butterfly" ? 0 : 1) : undefined,
        hoverOnly,
      });
      observer = new ResizeObserver(() => motionRef.current?.redraw());
      observer.observe(canvas);
    } catch {
      setUnavailable(true);
      dispose();
    }
    return cleanup;
  }, [shape, hoverOnly, accented, contextGeneration]);

  useEffect(() => { motionRef.current?.setPaused(paused); }, [paused]);

  // Without WebGL, show the resting frame drawn with Canvas 2D instead of a blank card.
  useEffect(() => {
    const fallback = fallbackRef.current;
    if (!unavailable || !fallback) return;
    const shapes: ParticleShape[] = shape ? [shape] : ["butterfly", "infinity"];
    const draw = () => { drawParticleFallback(fallback, shapes, accented); };
    draw();
    const observer = new ResizeObserver(draw);
    observer.observe(fallback);
    return () => observer.disconnect();
  }, [unavailable, shape, accented]);

  return <span className={className} aria-hidden={shape ? true : undefined}>
    <canvas ref={canvasRef} role="img" hidden={unavailable} aria-label={shape ? undefined : "Silver particle butterfly and silver particle infinity loop"} />
    {unavailable && <canvas ref={fallbackRef} data-particle-fallback="" aria-hidden="true" />}
    {/* Only the design lab surfaces the failure; product pages rely on the static fallback. */}
    {unavailable && !shape && <span className="particle-study__error">The artwork could not load. Check your connection and WebGL support, then reload.</span>}
  </span>;
}
