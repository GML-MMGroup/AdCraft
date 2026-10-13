import { useState } from "react";
import { ParticleIconStudy } from "../features/mode-icon-lab/ParticleIconStudy";
import "./particle-icon-study.css";

export function ModeIconLabPrototypePage() {
  const [paused, setPaused] = useState(false);
  return <main className="particle-study">
    <header className="particle-study__header"><span>ADCRAFT / DESIGN LAB</span><span>PARTICLE STUDIES — 01</span></header>
    <section className="particle-study__intro">
      <p>FORM IN MOTION</p>
      <h1>A different kind of presence.</h1>
      <span>Two identities, drawn in particles. Hover to explore the motion of each identity.</span>
    </section>
    <section className="particle-study__gallery" aria-label="Creation mode particle designs">
      <div className="particle-study__numbers"><span>01 / BUTTERFLY</span><span>02 / INFINITY</span></div>
      <div className="particle-study__controls"><button type="button" aria-pressed={paused} onClick={() => setPaused(value => !value)}>{paused ? "Resume motion" : "Pause motion"}</button></div>
      <ParticleIconStudy paused={paused} />
      <div className="particle-study__captions">
        <article><h2>Personal Creation</h2><p>Silver dust. Translucent wings. An individual expression.</p></article>
        <article><h2>Brand Professional</h2><p>Silver dust. Interwoven paths. A continuous identity.</p></article>
      </div>
    </section>
    <footer className="particle-study__footer"><span>MOTION STUDY · WEBGL</span><span>White / silver grey · Gentle motion</span></footer>
  </main>;
}
