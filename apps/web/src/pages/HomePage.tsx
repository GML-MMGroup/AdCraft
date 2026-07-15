import { useState } from "react";
import type { CSSProperties } from "react";
import { useApp } from "../AppContextValue";
import { SectionTitle } from "../components/Cards";
import { HomePromptComposer, type HomePromptGenerateContext } from "../components/HomePromptComposer";
import { PlanningErrorNotice } from "../components/PlanningErrorNotice";
import { demoProjects, images, imageSrc } from "../data";
import { PlayIcon } from "../icons";
import type { FrontDeskMessage, RouteName } from "../types";
import type { V2InputAssetUploadItem } from "../types-v2.ts";
import type { PlanningFailureState } from "./homeWorkflowPlanning";

type PendingPlanningRequest = {
  prompt: string;
  context: HomePromptGenerateContext;
  history: FrontDeskMessage[];
};

export function HomePage({ navigate }: { navigate: (route: RouteName) => void }) {
  const [modalOpen, setModalOpen] = useState(false);
  const [planningError, setPlanningError] = useState<PlanningFailureState | null>(null);
  const [pendingPlanningRequest, setPendingPlanningRequest] = useState<PendingPlanningRequest | null>(null);
  const { messages, promptLibraryEntities, setMessages, setWorkflow } = useApp();

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

  async function uploadPromptInputAsset(file: File): Promise<V2InputAssetUploadItem[]> {
    const { v2Api } = await import("../api/v2Client");
    const formData = new FormData();
    formData.append("files[]", file);
    formData.append("intent", "product_reference");
    const response = await v2Api.uploadInputAssets(formData);
    return response.assets;
  }

  async function generate(prompt: string, context: HomePromptGenerateContext = {}, retry = false) {
    const history = retry && pendingPlanningRequest ? pendingPlanningRequest.history : messages;
    const nextMessages = retry ? messages : [...messages, { role: "user" as const, content: prompt }];
    if (!retry) setMessages(nextMessages);
    setPlanningError(null);

    try {
      const { planHomeWorkflow } = await import("./homeWorkflowPlanning");
      const response = await planHomeWorkflow({
        prompt,
        history,
        inputAssets: [...(context.input_asset_locators ?? []), ...(context.asset_locators ?? [])],
        libraryEntities: promptLibraryEntities,
      });
      setMessages([...nextMessages, { role: "assistant", content: response.reply }]);
      if (response.workflow) {
        setWorkflow(response.workflow);
        navigate("workflow");
      } else if (!response.shouldStartWorkflow) {
        navigate("workflow");
      }
      setPendingPlanningRequest(null);
    } catch (error) {
      const { planningFailureState } = await import("./homeWorkflowPlanning");
      setPlanningError(planningFailureState(error));
      setPendingPlanningRequest({ prompt, context, history });
    }
  }

  function retryPlanning() {
    if (pendingPlanningRequest) void generate(pendingPlanningRequest.prompt, pendingPlanningRequest.context, true);
  }

  return (
    <>
      <section className="hero">
        <div>
          <p className="hero-copy">Describe a scene, attach references, and continue into a workflow canvas designed for video generation.</p>
          <HomePromptComposer
            placeholder="Describe the product film you want to create..."
            onGenerate={generate}
            onUploadInputAsset={uploadPromptInputAsset}
          />
          {planningError ? <PlanningErrorNotice error={planningError} onRetry={retryPlanning} /> : null}
          <div className="mode-row">
            {["Video", "Image", "Storyboard", "Character", "Scene"].map((mode, index) => (
              <button key={mode} className={`mode ${index === 0 ? "is-active" : ""}`}>
                {mode}
              </button>
            ))}
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
    </>
  );
}
