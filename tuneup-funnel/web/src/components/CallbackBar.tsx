import { useState } from "react";
import { PHONE_DISPLAY, PHONE_TEL } from "../content";
import { requestCallback } from "../api";
import type { FunnelState } from "../types";

/**
 * Persistent "Prefer to talk? Request a call" bar on every gate (build spec,
 * older-user accessibility). Opening the form is also triggered automatically
 * when the user stalls on the photo step (handled by the parent).
 */
export function CallbackBar({
  state,
  open,
  setOpen,
}: {
  state: FunnelState;
  open: boolean;
  setOpen: (v: boolean) => void;
}) {
  return (
    <>
      <div className="callback-fab">
        <div className="inner">
          <button className="btn secondary" onClick={() => setOpen(true)}>
            Prefer to talk? Request a call
          </button>
        </div>
      </div>
      {open && <CallbackModal state={state} onClose={() => setOpen(false)} />}
    </>
  );
}

function CallbackModal({ state, onClose }: { state: FunnelState; onClose: () => void }) {
  // Pre-fill from the contact gate if we already have it (build spec: session
  // saved so the caller sees ZIP/openings/photos already provided).
  const [name, setName] = useState(state.contact.name);
  const [phone, setPhone] = useState(state.contact.phone);
  const [bestTime, setBestTime] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    try {
      await requestCallback({ sessionId: state.sessionId, name, phone, bestTime });
    } catch {
      /* still show success — team also gets the partial session */
    }
    setSent(true);
    setBusy(false);
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        {sent ? (
          <div className="stack center">
            <h2>You're all set 👍</h2>
            <p>
              Our team will call you{bestTime ? ` ${bestTime}` : " shortly"}. We already have the
              details you entered, so we can pick up right where you left off.
            </p>
            <a className="btn" href={`tel:${PHONE_TEL}`}>
              Or call us now: {PHONE_DISPLAY}
            </a>
            <button className="btn ghost" onClick={onClose}>
              Close
            </button>
          </div>
        ) : (
          <div className="stack">
            <h2>Request a call</h2>
            <p className="muted">Tell us when's best and we'll reach out. No obligation.</p>
            <label>
              Your name
              <input type="text" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
            </label>
            <label>
              Phone
              <input type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} autoComplete="tel" inputMode="tel" />
            </label>
            <label>
              Best time to reach you
              <input
                type="text"
                value={bestTime}
                onChange={(e) => setBestTime(e.target.value)}
                placeholder="e.g. weekday mornings"
              />
            </label>
            <button className="btn" disabled={busy || !name || phone.length < 10} onClick={submit}>
              {busy ? "Sending…" : "Request my call"}
            </button>
            <a className="btn ghost" href={`tel:${PHONE_TEL}`}>
              Call now instead: {PHONE_DISPLAY}
            </a>
            <button className="btn ghost" onClick={onClose}>
              Never mind
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
