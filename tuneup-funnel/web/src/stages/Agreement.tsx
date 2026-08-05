import { useState } from "react";
import type { Action } from "../App";
import type { FunnelState } from "../types";
import { AGREEMENT_SECTIONS, HIC_NUMBER } from "../agreement";
import { recordAgreement, saveProgress } from "../api";

/**
 * Scrollable service agreement + e-consent. Mirrors the SM proposal text (owner
 * supplies) and carries the NJ HIC requirements: registration number, dates,
 * total price, and the 3-day right of rescission. The consent checkbox unlocks
 * only after the customer scrolls to the end.
 */
export function Agreement({
  state,
  dispatch,
  onNext,
}: {
  state: FunnelState;
  dispatch: React.Dispatch<Action>;
  onNext: () => void;
}) {
  const [scrolledEnd, setScrolledEnd] = useState(false);
  const [agreed, setAgreed] = useState(false);
  const [busy, setBusy] = useState(false);

  const onScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    if (el.scrollTop + el.clientHeight >= el.scrollHeight - 24) setScrolledEnd(true);
  };

  const accept = async () => {
    setBusy(true);
    if (state.sessionId) {
      await recordAgreement(state.sessionId, state.contact.name).catch(() => {});
      saveProgress(state.sessionId, { stage: "agreement" }).catch(() => {});
    }
    dispatch({ type: "patch", patch: {} });
    setBusy(false);
    onNext();
  };

  return (
    <div className="stage stack">
      <div className="card">
        <h1>Your service agreement</h1>
        <p className="muted">
          Please read and accept before your deposit. NJ HIC Reg. #{HIC_NUMBER}.
        </p>
        <div
          onScroll={onScroll}
          style={{
            maxHeight: 340,
            overflowY: "auto",
            border: "1px solid var(--line)",
            borderRadius: 12,
            padding: 14,
            background: "#fffdfb",
          }}
        >
          {AGREEMENT_SECTIONS.map((s) => (
            <section key={s.heading} style={{ marginBottom: 14 }}>
              <h3 style={{ fontSize: "1.05rem", marginBottom: 4 }}>{s.heading}</h3>
              <p style={{ fontSize: "0.92rem", margin: 0 }}>{s.body}</p>
            </section>
          ))}
          <p className="muted" style={{ fontSize: "0.8rem" }}>
            You'll receive a copy of this agreement by email. Your invoice arrives from
            ServiceMinder.
          </p>
        </div>
        {!scrolledEnd && <p className="muted center">Scroll to the end to continue ↓</p>}

        <label style={{ display: "flex", gap: 10, alignItems: "flex-start", marginTop: 14 }}>
          <input
            type="checkbox"
            checked={agreed}
            disabled={!scrolledEnd}
            onChange={(e) => setAgreed(e.target.checked)}
            style={{ width: 24, height: 24, marginTop: 2 }}
          />
          <span style={{ fontWeight: 600 }}>
            I have read and agree to the service agreement above, including the 3-day right to
            cancel.
          </span>
        </label>
      </div>

      <button className="btn" disabled={!agreed || busy} onClick={accept}>
        {busy ? "One moment…" : "Agree & continue to deposit"}
      </button>
    </div>
  );
}
