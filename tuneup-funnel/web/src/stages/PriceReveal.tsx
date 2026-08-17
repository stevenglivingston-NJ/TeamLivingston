import { useEffect, useRef, useState } from "react";
import type { Action } from "../App";
import type { FunnelState, QuoteReveal } from "../types";
import { FIRM_PRICE_COPY, PHONE_DISPLAY, PHONE_TEL } from "../content";
import { classifyPhotos, formatUsd, previewQuote, saveProgress, uploadPhoto } from "../api";

const LEVEL_COPY: Record<string, string> = {
  L1_2: "Your cabinets show light-to-moderate finish wear — a Basic Tune-Up restores the finish and sheen.",
  L3: "Your cabinets have deeper wear into the wood in spots — a Standard Tune-Up with targeted repairs brings them back.",
  L4: "Your cabinets show heavier wear across much of the surface — this needs our advanced Tune-Up work.",
};

type Phase = "working" | "instant" | "human" | "error";

export function PriceReveal({
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
  const [phase, setPhase] = useState<Phase>("working");
  const [reveal, setReveal] = useState<QuoteReveal | null>(state.quote);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function run() {
    try {
      const sessionId = state.sessionId;
      // 1. Upload captured photos to R2 (best effort).
      const keys: string[] = [];
      if (sessionId) {
        for (const p of state.photos) {
          if (p.file) {
            const res = await uploadPhoto(sessionId, p.key, p.file);
            if ("key" in res) keys.push(res.key);
          }
        }
      }
      if (keys.length === 0) return toHuman(["photos not available for analysis"]);

      // 2. Classify.
      const outcome = await classifyPhotos(keys, state.openings);
      if (outcome.route === "human_review" || !outcome.result) {
        return toHuman(outcome.reasons ?? ["needs a closer look"]);
      }

      // 3. Price from the assigned level.
      const price = await previewQuote({
        openings: state.openings,
        level: outcome.result.level,
        whiteWash: outcome.result.whiteWash,
      });
      if (!price.quotable || price.quoteCents == null) {
        return toHuman(price.reasons ?? ["pricing not available"]);
      }

      const result: QuoteReveal = {
        quotable: true,
        quoteCents: price.quoteCents,
        depositCents: price.depositCents,
        floorApplied: price.floorApplied,
        whiteWashCents: price.whiteWashCents ?? null,
        level: outcome.result.level,
        reasoning: LEVEL_COPY[outcome.result.level] ?? outcome.result.conditionNotes,
        humanReview: false,
      };
      setReveal(result);
      dispatch({ type: "patch", patch: { quote: result } });
      if (sessionId) {
        saveProgress(sessionId, {
          stage: "price",
          level: result.level,
          quote_cents: result.quoteCents,
          deposit_cents: result.depositCents,
          floor_applied: result.floorApplied ? 1 : 0,
          white_wash: result.whiteWashCents ? 1 : 0,
        }).catch(() => {});
      }
      setPhase("instant");
    } catch {
      toHuman(["we couldn't finish the automatic estimate"]);
    }
  }

  function toHuman(reasons: string[]) {
    const result: QuoteReveal = { quotable: false, humanReview: true, reasons };
    setReveal(result);
    dispatch({ type: "patch", patch: { quote: result } });
    if (state.sessionId) {
      saveProgress(state.sessionId, { stage: "price", status: "human_review" }).catch(() => {});
    }
    setPhase("human");
  }

  if (phase === "working") {
    return (
      <div className="stage">
        <div className="card center stack">
          <h1>Preparing your price…</h1>
          <p className="muted">We're reviewing your photos. This takes just a moment.</p>
          <div className="progress-track" style={{ maxWidth: 240, margin: "0 auto" }}>
            <div className="progress-fill" style={{ width: "70%" }} />
          </div>
        </div>
      </div>
    );
  }

  if (phase === "human" || !reveal || reveal.humanReview) {
    return (
      <div className="stage">
        <div className="card stack">
          <h1>Your quote is being finalized</h1>
          <p>
            Thanks{state.contact.name ? `, ${state.contact.name.split(" ")[0]}` : ""}! A few of your
            photos need a quick look from our team to price them accurately. We'll have your quote to
            you <strong>within 2 hours</strong> by text and email.
          </p>
          <div className="notice">
            Want it faster? Give us a call and we can often price it on the spot.
          </div>
          <a className="btn" href={`tel:${PHONE_TEL}`}>
            Call us: {PHONE_DISPLAY}
          </a>
          <button className="btn ghost" onClick={onCallback}>
            Have us call you instead
          </button>
        </div>
      </div>
    );
  }

  // Instant quote.
  const total = reveal.quoteCents!;
  const deposit = reveal.depositCents!;
  return (
    <div className="stage stack">
      <div className="card">
        <div className="price-hero">
          <div className="sub">Your firm Tune-Up price</div>
          <div className="amount">{formatUsd(total)}</div>
          {reveal.floorApplied && <div className="sub">Our $2,000 project minimum applies</div>}
        </div>
        <p style={{ marginTop: 14 }}>{reveal.reasoning}</p>
        <div className="line-items">
          {reveal.whiteWashCents ? (
            <div className="row">
              <span>Includes white-wash finish premium</span>
              <span>{formatUsd(reveal.whiteWashCents)}</span>
            </div>
          ) : null}
          <div className="row total">
            <span>Total</span>
            <span>{formatUsd(total)}</span>
          </div>
          <div className="row">
            <span>Due today (50% deposit)</span>
            <span>{formatUsd(deposit)}</span>
          </div>
        </div>
        <div className="firm-note">{FIRM_PRICE_COPY}</div>
      </div>

      <button className="btn" onClick={onNext}>
        Pick my appointment time
      </button>
      <button className="btn ghost" onClick={onCallback}>
        Questions? Request a call
      </button>
    </div>
  );
}
