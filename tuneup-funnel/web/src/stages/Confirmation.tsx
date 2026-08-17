import type { FunnelState } from "../types";
import { formatUsd } from "../api";
import { PHONE_DISPLAY, PHONE_TEL } from "../content";

export function Confirmation({ state }: { state: FunnelState }) {
  const slot = state.selectedSlot ? new Date(state.selectedSlot) : null;
  const when = slot
    ? slot.toLocaleString("en-US", {
        weekday: "long",
        month: "long",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      })
    : null;
  const total = state.quote?.quoteCents ?? 0;
  const deposit = state.quote?.depositCents ?? 0;

  return (
    <div className="stage">
      <div className="card stack center">
        <div style={{ fontSize: "3rem" }}>🎉</div>
        <h1>You're booked!</h1>
        <p>
          Thanks{state.contact.name ? `, ${state.contact.name.split(" ")[0]}` : ""} — your Kitchen
          Tune-Up is reserved.
        </p>

        <div className="line-items" style={{ textAlign: "left", width: "100%" }}>
          {when && (
            <div className="row">
              <span>Appointment</span>
              <span>{when}</span>
            </div>
          )}
          <div className="row">
            <span>Total price</span>
            <span>{formatUsd(total)}</span>
          </div>
          <div className="row">
            <span>Deposit</span>
            <span>{formatUsd(deposit)}</span>
          </div>
          <div className="row">
            <span>Balance at completion</span>
            <span>{formatUsd(total - deposit)}</span>
          </div>
        </div>

        <div className="notice" style={{ textAlign: "left" }}>
          <strong>What's next:</strong> your invoice arrives from ServiceMinder, and you'll get a
          confirmation by email and text. If anything's not visible in your photos, we'll send any
          price adjustment for your approval before we start. You have 3 business days to cancel for
          a full refund.
        </div>

        <a className="btn" href={`tel:${PHONE_TEL}`}>
          Questions? Call us: {PHONE_DISPLAY}
        </a>
      </div>
    </div>
  );
}
