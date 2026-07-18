import { PHONE_DISPLAY, PHONE_TEL } from "../content";

/**
 * Phase 4 wires live ServiceMinder "Tune-Up Residential" calendar slots, the
 * scrollable service agreement (NJ HIC + 3-day rescission), and Stripe Checkout
 * for the 50% deposit here. For now this is the hand-off point.
 */
export function SchedulePlaceholder() {
  return (
    <div className="stage">
      <div className="card stack center">
        <h1>You're almost booked! 🎉</h1>
        <p>
          Online scheduling and secure deposit checkout are being finalized. In the meantime, our
          team will reach out to lock in your appointment — or call us now and we'll book you on the
          spot.
        </p>
        <a className="btn" href={`tel:${PHONE_TEL}`}>
          Call to book: {PHONE_DISPLAY}
        </a>
        <p className="muted">Your quote and photos are saved — we'll pick up right where you left off.</p>
      </div>
    </div>
  );
}
