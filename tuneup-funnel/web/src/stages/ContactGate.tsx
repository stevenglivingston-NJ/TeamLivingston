import { useState } from "react";
import type { Action } from "../App";
import type { FunnelState } from "../types";
import { submitLead, saveProgress } from "../api";

/**
 * Name / phone / email are REQUIRED before the price reveal. The lead fires to
 * the backend on submit (which fans out to HighLevel in Phase 5). We proceed to
 * the price screen even if the network call fails — the customer isn't blocked.
 */
export function ContactGate({
  state,
  dispatch,
  onNext,
}: {
  state: FunnelState;
  dispatch: React.Dispatch<Action>;
  onNext: () => void;
}) {
  const [name, setName] = useState(state.contact.name);
  const [phone, setPhone] = useState(state.contact.phone);
  const [email, setEmail] = useState(state.contact.email);
  const [busy, setBusy] = useState(false);
  const [touched, setTouched] = useState(false);

  const phoneOk = phone.replace(/\D/g, "").length >= 10;
  const emailOk = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email);
  const nameOk = name.trim().length >= 2;
  const valid = nameOk && phoneOk && emailOk;

  const submit = async () => {
    setTouched(true);
    if (!valid) return;
    setBusy(true);
    const contact = { name: name.trim(), phone, email };
    dispatch({ type: "patch", patch: { contact } });
    if (state.sessionId) {
      submitLead(state.sessionId, contact).catch(() => {});
      saveProgress(state.sessionId, { stage: "contact" }).catch(() => {});
    }
    setBusy(false);
    onNext();
  };

  return (
    <div className="stage">
      <div className="card stack">
        <h1>Almost there — where do we send your price?</h1>
        <p className="muted">We'll show your price on the next screen and email you a copy.</p>

        <label>
          Full name
          <input type="text" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
          {touched && !nameOk && <div className="field-error">Please enter your name.</div>}
        </label>
        <label>
          Phone
          <input
            type="tel"
            inputMode="tel"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            autoComplete="tel"
            placeholder="(973) 555-0123"
          />
          {touched && !phoneOk && <div className="field-error">Please enter a valid phone number.</div>}
        </label>
        <label>
          Email
          <input
            type="email"
            inputMode="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
            placeholder="you@email.com"
          />
          {touched && !emailOk && <div className="field-error">Please enter a valid email.</div>}
        </label>

        <button className="btn" disabled={busy} onClick={submit}>
          {busy ? "One moment…" : "Show my price"}
        </button>
        <p className="muted center" style={{ marginBottom: 0 }}>
          We respect your privacy. Your photos are used only to prepare your quote.
        </p>
      </div>
    </div>
  );
}
