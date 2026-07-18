import { useState } from "react";
import type { Action } from "../App";
import type { FunnelState } from "../types";
import { SERVICE_ZIP_PREFIXES, PHONE_DISPLAY, PHONE_TEL } from "../content";
import { saveProgress } from "../api";

export function ZipGate({
  state,
  dispatch,
  onNext,
  onCallback,
}: {
  state: FunnelState;
  dispatch: React.Dispatch<Action>;
  onNext: () => void;
  onCallback: () => void;
}) {
  const [zip, setZip] = useState(state.zip);
  const [checked, setChecked] = useState<null | boolean>(null);

  const check = () => {
    const inArea = SERVICE_ZIP_PREFIXES.some((p) => zip.startsWith(p));
    setChecked(inArea);
    dispatch({ type: "patch", patch: { zip, inServiceArea: inArea } });
    if (state.sessionId) {
      saveProgress(state.sessionId, {
        zip,
        in_service_area: inArea ? 1 : 0,
        status: inArea ? "open" : "out_of_area",
      }).catch(() => {});
    }
  };

  const valid = /^\d{5}$/.test(zip);

  return (
    <div className="stage">
      <div className="card stack">
        <h1>First, let's check your area</h1>
        <p className="muted">Enter your ZIP code so we can confirm we serve you.</p>
        <label htmlFor="zip">
          ZIP code
          <input
            id="zip"
            type="text"
            inputMode="numeric"
            autoComplete="postal-code"
            maxLength={5}
            value={zip}
            onChange={(e) => {
              setZip(e.target.value.replace(/\D/g, ""));
              setChecked(null);
            }}
            placeholder="07003"
          />
        </label>

        {checked === null && (
          <button className="btn" disabled={!valid} onClick={check}>
            Check my area
          </button>
        )}

        {checked === true && (
          <>
            <div className="notice">Great news — we serve your area! ✅</div>
            <button className="btn" onClick={onNext}>
              Continue
            </button>
          </>
        )}

        {checked === false && (
          <>
            <div className="notice" style={{ background: "#fdf1ec", borderColor: "#f3d6c4", color: "#7a3413" }}>
              We may be just outside your area — but we'd still love to help. Leave your info and
              we'll see what we can do.
            </div>
            <button className="btn" onClick={onCallback}>
              Have us reach out
            </button>
            <a className="btn ghost" href={`tel:${PHONE_TEL}`}>
              Or call: {PHONE_DISPLAY}
            </a>
          </>
        )}
      </div>
    </div>
  );
}
