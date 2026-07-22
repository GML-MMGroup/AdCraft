import { useState } from "react";
import type { CSSProperties } from "react";
import { useApp } from "../AppContextValue";
import { SectionTitle } from "../components/Cards";
import { demoProjects, images, imageSrc } from "../data";
import { PlayIcon, PlusIcon } from "../icons";
import type { RouteName } from "../types";

export function HomePage({ navigate }: { navigate: (route: RouteName) => void }) {
  const [modalOpen, setModalOpen] = useState(false);
  const { startNewProject } = useApp();

  const discoverCards: Array<[string, string, number]> = [
    ["Campaign Flow", images[0], 240],
    ["Character Study", images[1], 330],
    ["Poster Motion", images[2], 260],
    ["Scene Extension", images[3], 370],
    ["Product Aura", images[4], 280],
    ["Editorial Cut", images[5], 320],
    ["Portrait Spark", images[6], 260],
    ["Color Script", images[7], 350],
  ];

  function createProject() {
    startNewProject();
    navigate("workflow");
  }

  return (
    <div className="home-page">
      <section className="home-product-hero" aria-labelledby="home-product-title">
        <div className="home-product-hero__content">
          <h1 className="home-product-hero__title" id="home-product-title" aria-label="One Sentence Becomes an Ad film.">
            <span>One Sentence Becomes an</span>{" "}
            <span className="home-product-hero__accent">Ad film.</span>
          </h1>
          <p className="home-product-hero__description">
            AdCraft — The first agentic video production platform for marketing and advertising. Infinite canvas · shot-by-shot replication · fully automated, from idea to final cut.
          </p>
          <button className="home-product-hero__create" type="button" onClick={createProject}>
            <PlusIcon />
            <span>Create Your Project</span>
          </button>
        </div>

        <div className="home-product-film" role="img" aria-label="product introduction video placeholder" data-media-slot="product-introduction">
          <img src="/assets/card1.webp" alt="" />
          <div className="home-product-film__frame" aria-hidden="true">
            <span className="home-product-film__play"><PlayIcon /></span>
          </div>
        </div>
      </section>

      <section className="content-wrap">
        <SectionTitle title="Recent Projects" subtitle="Pick up the latest creative thread." />
        <div className="recent-strip">
          <button className="recent-card featured" onClick={() => navigate("workflow")}>
            <div className="featured-glass">
              <h3>New fragrance product reel</h3>
              <p>Continue editing the current workflow canvas.</p>
            </div>
          </button>
          {demoProjects.slice(0, 3).map((project) => (
            <button key={project.name} className="recent-card" onClick={() => navigate("workflow")}>
              <h3>{project.name}</h3>
              <p>{project.time}</p>
            </button>
          ))}
        </div>

        <SectionTitle title="Discover" subtitle="References, templates, and generated video ideas." />
        <div className="discover-tabs">
          {["All", "Product", "Portrait", "Scene", "Motion"].map((tab, index) => (
            <button key={tab} className={`filter-btn ${index === 0 ? "is-active" : ""}`}>
              {tab}
            </button>
          ))}
        </div>
        <div className="waterfall">
          {discoverCards.map(([title, img, height]) => (
            <button
              key={title}
              className="discover-card"
              style={{ "--h": `${height}px` } as CSSProperties}
              data-title={title}
              onClick={() => setModalOpen(true)}
            >
              <img className="discover-card-image" src={imageSrc(img)} alt="" loading="lazy" decoding="async" />
              <span className="play-dot">
                <span>
                  <PlayIcon />
                </span>
              </span>
            </button>
          ))}
        </div>
      </section>

      <div className={`video-modal ${modalOpen ? "is-open" : ""}`}>
        <div className="modal-card">
          <div className="modal-preview">
            <PlayIcon />
          </div>
          <div className="composer-footer" style={{ marginTop: 14 }}>
            <strong>Preview Case</strong>
            <button className="small-action" onClick={() => setModalOpen(false)}>
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
