import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import { DiscoverOrbit } from "../../src/pages/DiscoverOrbit";
import { images, imageSrc } from "../../src/data";
import "../../src/pages/home.css";

const items = images.slice(0, 8).map((image, index) => ({
  title: `Inspiration ${index + 1}`,
  image: imageSrc(image),
}));

function DiscoverMotionFixture() {
  const [selections, setSelections] = useState(0);
  return (
    <>
      <output aria-label="Selection count">{selections}</output>
      <div className="fixture-spacer" />
      <main>
        <DiscoverOrbit items={items} interactive onSelect={() => setSelections((count) => count + 1)} />
      </main>
      <div className="fixture-spacer" />
    </>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><DiscoverMotionFixture /></StrictMode>);
