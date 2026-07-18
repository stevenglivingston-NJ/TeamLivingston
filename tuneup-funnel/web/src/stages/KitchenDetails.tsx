import { useState } from "react";
import type { Action } from "../App";
import type { FunnelState } from "../types";
import { saveProgress } from "../api";

const MATERIALS = ["Wood", "Painted", "Laminate/Thermofoil", "Not sure"];
const AGES = ["Under 10 yrs", "10–20 yrs", "20+ yrs", "Not sure"];
const YESNO: Array<{ v: "yes" | "no" | "unsure"; label: string }> = [
  { v: "no", label: "No" },
  { v: "yes", label: "Yes" },
  { v: "unsure", label: "Not sure" },
];

export function KitchenDetails({
  state,
  dispatch,
  onNext,
}: {
  state: FunnelState;
  dispatch: React.Dispatch<Action>;
  onNext: () => void;
}) {
  const [openings, setOpenings] = useState(state.openings);
  const [material, setMaterial] = useState(state.cabinetMaterial);
  const [age, setAge] = useState(state.cabinetAge);
  const [smoking, setSmoking] = useState(state.smokingInHome);
  const [polish, setPolish] = useState(state.polishProductsUsed);

  const ready = material !== "" && age !== "" && smoking !== "" && polish !== "";

  const next = () => {
    const patch = {
      openings,
      cabinetMaterial: material,
      cabinetAge: age,
      smokingInHome: smoking,
      polishProductsUsed: polish,
    };
    dispatch({ type: "patch", patch });
    if (state.sessionId) {
      saveProgress(state.sessionId, {
        openings,
        cabinet_material: material,
        cabinet_age: age,
        smoking_in_home: smoking,
        polish_products: polish,
      }).catch(() => {});
    }
    onNext();
  };

  return (
    <div className="stage stack">
      <div className="card">
        <h1>Tell us about your kitchen</h1>
        <label>
          How many cabinet doors and drawer fronts?
          <span className="hint">
            Count each door and each drawer front. A typical kitchen has 15–30. Don't worry about
            being exact — we'll confirm from your photos.
          </span>
        </label>
        <div className="counter" aria-label="Opening count">
          <button aria-label="Fewer" onClick={() => setOpenings((n) => Math.max(1, n - 1))}>
            −
          </button>
          <span className="value">{openings}</span>
          <button aria-label="More" onClick={() => setOpenings((n) => Math.min(80, n + 1))}>
            +
          </button>
        </div>
      </div>

      <div className="card">
        <label>What are your cabinets made of?</label>
        <div className="chips">
          {MATERIALS.map((m) => (
            <button key={m} className="chip" aria-pressed={material === m} onClick={() => setMaterial(m)}>
              {m}
            </button>
          ))}
        </div>

        <label>About how old are they?</label>
        <div className="chips">
          {AGES.map((a) => (
            <button key={a} className="chip" aria-pressed={age === a} onClick={() => setAge(a)}>
              {a}
            </button>
          ))}
        </div>
      </div>

      <div className="card">
        {/* These two questions come from the KTU sales-training doc: both can raise
            the damage level and aren't always visible in photos. */}
        <label>Has anyone smoked in the home?</label>
        <div className="chips">
          {YESNO.map((o) => (
            <button key={o.v} className="chip" aria-pressed={smoking === o.v} onClick={() => setSmoking(o.v)}>
              {o.label}
            </button>
          ))}
        </div>

        <label>
          Have polish or touch-up products been used on the cabinets?
          <span className="hint">Things like Old English, scratch cover, or Liquid Gold.</span>
        </label>
        <div className="chips">
          {YESNO.map((o) => (
            <button key={o.v} className="chip" aria-pressed={polish === o.v} onClick={() => setPolish(o.v)}>
              {o.label}
            </button>
          ))}
        </div>
      </div>

      <button className="btn" disabled={!ready} onClick={next}>
        Next: add photos
      </button>
    </div>
  );
}
