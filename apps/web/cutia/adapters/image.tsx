import type { ImgHTMLAttributes } from "react";

export default function Image({ fill, priority: _priority, unoptimized: _unoptimized, ...props }: ImgHTMLAttributes<HTMLImageElement> & { fill?: boolean; priority?: boolean; unoptimized?: boolean }) {
  return <img {...props} alt={props.alt || ""} style={{ ...(fill ? { position: "absolute", width: "100%", height: "100%", inset: 0 } : {}), ...props.style }} />;
}
