import { useEffect, useState } from "react";
import type { Action } from "../App";
import type { FunnelState } from "../types";
import { fetchSlots, saveProgress, type SlotsResult } from "../api";
import { PHONE_DISPLAY, PHONE_TEL } from "../content";

function nextDays(count: number): string[] {
  const out: string[] = [];
  const d = new Date();
  for (let i = 1; out.length < count; i++) {
    const day = new Date(d.getTime() + i * 86_400_000);
    // Skip Sundays.
    if (day.getDay() !== 0) out.push(day.toISOString().slice(0, 10));
  }
  return out;
}

function fmtDate(iso: string): string {
  return new Date(iso + "T12:00:00").toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}
function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
}

export function Schedule({
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
  const days = nextDays(6);
  const [date, setDate] = useState(days[0]);
  const [result, setResult] = useState<SlotsResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [addr, setAddr] = useState(state.address);

  useEffect(() => {
    setLoading(true);
    fetchSlots(date, state.openings)
      .then(setResult)
      .catch(() => setResult({ durationMinutes: 240, available: false, slots: [] }))
      .finally(() => setLoading(false));
  }, [date, state.openings]);

  const addrOk = addr.address1.trim().length > 3 && addr.city.trim() && /^\d{5}$/.test(addr.zip);

  const pick = (start: string) => {
    dispatch({ type: "patch", patch: { selectedSlot: start, address: addr } });
    if (state.sessionId) saveProgress(state.sessionId, { stage: "schedule" }).catch(() => {});
    onNext();
  };

  return (
    <div className="stage stack">
      <div className="card">
        <h1>Pick your appointment</h1>
        <p className="muted">Your Tune-Up takes about one day. Choose a date to see open times.</p>

        <label>Service address</label>
        <input
          type="text"
          placeholder="Street address"
          value={addr.address1}
          onChange={(e) => setAddr({ ...addr, address1: e.target.value })}
          autoComplete="address-line1"
        />
        <div style={{ display: "flex", gap: 10, marginTop: 10 }}>
          <input
            type="text"
            placeholder="City"
            value={addr.city}
            onChange={(e) => setAddr({ ...addr, city: e.target.value })}
            autoComplete="address-level2"
          />
          <input
            type="text"
            placeholder="ZIP"
            inputMode="numeric"
            maxLength={5}
            value={addr.zip || state.zip}
            onChange={(e) => setAddr({ ...addr, zip: e.target.value.replace(/\D/g, "") })}
            style={{ maxWidth: 120 }}
          />
        </div>
      </div>

      <div className="card">
        <label>Choose a date</label>
        <div className="chips">
          {days.map((d) => (
            <button key={d} className="chip" aria-pressed={date === d} onClick={() => setDate(d)}>
              {fmtDate(d)}
            </button>
          ))}
        </div>

        <div style={{ marginTop: 16 }}>
          {loading && <p className="muted">Checking open times…</p>}
          {!loading && result && result.slots.length > 0 && (
            <div className="stack">
              {result.slots.map((s) => (
                <button
                  key={s.start}
                  className="btn secondary"
                  disabled={!addrOk}
                  onClick={() => pick(s.start)}
                >
                  {fmtTime(s.start)}
                </button>
              ))}
              {!addrOk && <p className="muted">Enter your service address above to choose a time.</p>}
            </div>
          )}
          {!loading && result && result.slots.length === 0 && (
            <>
              <div className="notice">
                We schedule these personally to make sure we bring the right team and materials.
                Leave your details and we'll confirm your exact time — usually same day.
              </div>
              <button className="btn" style={{ marginTop: 12 }} disabled={!addrOk} onClick={() => pick(`${date}T09:00:00`)}>
                Request {fmtDate(date)}
              </button>
              <a className="btn ghost" href={`tel:${PHONE_TEL}`} style={{ marginTop: 10 }}>
                Or call to book: {PHONE_DISPLAY}
              </a>
            </>
          )}
        </div>
      </div>

      <button className="btn ghost" onClick={onCallback}>
        Prefer we call to schedule?
      </button>
    </div>
  );
}
