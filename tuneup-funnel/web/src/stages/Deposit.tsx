import { useState } from "react";
import type { Action } from "../App";
import type { FunnelState } from "../types";
import { confirmBooking, formatUsd, startDeposit } from "../api";
import { trackGa, trackMeta, trackingContext } from "../tracking";

/**
 * 50% deposit via the HighLevel payment integration. When HighLevel payments
 * are configured, we open the payment link and the HL webhook confirms the
 * booking server-side. Until that's wired, the funnel completes with a
 * "deposit invoice on its way" fallback so the customer still books.
 */
export function Deposit({
  state,
  dispatch,
  onNext,
}: {
  state: FunnelState;
  dispatch: React.Dispatch<Action>;
  onNext: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const deposit = state.quote?.depositCents ?? 0;
  const total = state.quote?.quoteCents ?? 0;

  const pay = async () => {
    if (!state.sessionId || !state.selectedSlot) return;
    setBusy(true);
    setError(null);
    try {
      // Checkout started: pixel + CAPI share this eventId (dedup pair).
      const checkoutTracking = trackingContext();
      trackMeta("InitiateCheckout", checkoutTracking.eventId, { value: deposit / 100, currency: "USD" });
      trackGa("begin_checkout", { value: deposit / 100, currency: "USD" });
      const res = await startDeposit(
        {
          sessionId: state.sessionId,
          depositCents: deposit,
          slotStart: state.selectedSlot,
        },
        checkoutTracking,
      );

      if (res.mode === "highlevel" && res.paymentUrl) {
        // Real payment: hand off to HighLevel; HL webhook books the appointment.
        window.location.href = res.paymentUrl;
        return;
      }

      // Fallback (HL payments not yet wired): still book the appointment and
      // let the team collect the deposit via a HighLevel invoice. The Purchase
      // pixel + CAPI event share one eventId; on the HL-redirect path only the
      // server-side event fires (the webhook confirms without this page).
      const purchaseTracking = trackingContext();
      trackMeta("Purchase", purchaseTracking.eventId, { value: deposit / 100, currency: "USD" });
      trackGa("purchase", {
        value: deposit / 100,
        currency: "USD",
        transaction_id: state.sessionId,
      });
      await confirmBooking({
        sessionId: state.sessionId,
        name: state.contact.name,
        phone: state.contact.phone,
        email: state.contact.email,
        address1: state.address.address1,
        city: state.address.city,
        state: state.address.state || "NJ",
        zip: state.address.zip || state.zip,
        scheduledStart: state.selectedSlot,
        openings: state.openings,
        quoteCents: total,
        depositCents: deposit,
        level: state.quote?.level,
        notes: `Online Tune-Up booking. Quote ${formatUsd(total)}, deposit ${formatUsd(deposit)}.`,
        ...purchaseTracking,
      }).catch(() => {});
      dispatch({ type: "patch", patch: {} });
      onNext();
    } catch {
      setError("Something went wrong starting your deposit. Please call us and we'll finish booking.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stage stack">
      <div className="card">
        <h1>Reserve your appointment</h1>
        <div className="line-items">
          <div className="row">
            <span>Total Tune-Up price</span>
            <span>{formatUsd(total)}</span>
          </div>
          <div className="row total">
            <span>Deposit due now (50%)</span>
            <span>{formatUsd(deposit)}</span>
          </div>
          <div className="row">
            <span>Balance at completion</span>
            <span>{formatUsd(total - deposit)}</span>
          </div>
        </div>
        <p className="muted" style={{ marginTop: 12 }}>
          Your deposit reserves your date. Your invoice arrives from ServiceMinder. Remember: you
          have 3 business days to cancel for a full refund.
        </p>
        {error && <div className="field-error">{error}</div>}
      </div>

      <button className="btn" disabled={busy || deposit <= 0} onClick={pay}>
        {busy ? "Processing…" : `Pay ${formatUsd(deposit)} deposit`}
      </button>
    </div>
  );
}
