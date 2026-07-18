import { useEffect, useReducer, useState } from "react";
import { PHOTO_SLOTS } from "./content";
import { createSession, saveProgress } from "./api";
import type { FunnelState, Stage } from "./types";
import { Header } from "./components/Header";
import { Progress } from "./components/Progress";
import { CallbackBar } from "./components/CallbackBar";
import { Landing } from "./stages/Landing";
import { ZipGate } from "./stages/ZipGate";
import { KitchenDetails } from "./stages/KitchenDetails";
import { PhotoCapture } from "./stages/PhotoCapture";
import { ContactGate } from "./stages/ContactGate";
import { PriceReveal } from "./stages/PriceReveal";
import { SchedulePlaceholder } from "./stages/SchedulePlaceholder";

const STAGES: Stage[] = ["landing", "zip", "details", "photos", "contact", "price", "schedule"];

const initialState: FunnelState = {
  sessionId: null,
  stage: "landing",
  zip: "",
  inServiceArea: null,
  openings: 12,
  cabinetMaterial: "",
  cabinetAge: "",
  smokingInHome: "",
  polishProductsUsed: "",
  photos: PHOTO_SLOTS.map((s) => ({ ...s })),
  contact: { name: "", phone: "", email: "" },
  quote: null,
};

export type Action =
  | { type: "patch"; patch: Partial<FunnelState> }
  | { type: "goto"; stage: Stage };

function reducer(state: FunnelState, action: Action): FunnelState {
  switch (action.type) {
    case "patch":
      return { ...state, ...action.patch };
    case "goto":
      return { ...state, stage: action.stage };
  }
}

export function App() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const [callbackOpen, setCallbackOpen] = useState(false);

  // Create the D1 session once, when the customer leaves the landing page.
  useEffect(() => {
    if (state.stage !== "landing" && state.sessionId === null) {
      createSession()
        .then(({ id }) => dispatch({ type: "patch", patch: { sessionId: id } }))
        .catch(() => {
          /* offline-tolerant: funnel continues without a server session */
        });
    }
  }, [state.stage, state.sessionId]);

  const goto = (stage: Stage) => {
    dispatch({ type: "goto", stage });
    window.scrollTo({ top: 0, behavior: "smooth" });
    if (state.sessionId) saveProgress(state.sessionId, { stage }).catch(() => {});
  };

  const stageIndex = STAGES.indexOf(state.stage);

  return (
    <>
      <Header />
      {state.stage !== "landing" && (
        <Progress current={stageIndex} total={STAGES.length - 1} stage={state.stage} />
      )}
      <main className="app">
        {state.stage === "landing" && <Landing onStart={() => goto("zip")} />}
        {state.stage === "zip" && <ZipGate state={state} dispatch={dispatch} onNext={() => goto("details")} onCallback={() => setCallbackOpen(true)} />}
        {state.stage === "details" && <KitchenDetails state={state} dispatch={dispatch} onNext={() => goto("photos")} />}
        {state.stage === "photos" && <PhotoCapture state={state} dispatch={dispatch} onNext={() => goto("contact")} onStall={() => setCallbackOpen(true)} />}
        {state.stage === "contact" && <ContactGate state={state} dispatch={dispatch} onNext={() => goto("price")} />}
        {state.stage === "price" && <PriceReveal state={state} dispatch={dispatch} onNext={() => goto("schedule")} onCallback={() => setCallbackOpen(true)} />}
        {state.stage === "schedule" && <SchedulePlaceholder />}
      </main>
      {state.stage !== "landing" && (
        <CallbackBar
          state={state}
          open={callbackOpen}
          setOpen={setCallbackOpen}
        />
      )}
    </>
  );
}
