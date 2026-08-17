import { useEffect, useState } from "react";
import type { Action } from "../App";
import type { FunnelState } from "../types";
import { fetchSlots, saveProgress, type SlotsResult } from "../api";
import { PHONE_DISPLAY, PHONE_TEL } from "../content";

/**
 * Saturday-first scheduling (owner 2026-08-11): tune-ups run primarily on
 * Saturdays, so offer the next 3 Saturdays up front and weekdays as the
 * secondary option. Sundays are never offered.
 */
function upcomingDates(): { saturdays: string[]; weekdays: string[] } {
  const saturdays: string[] = [];
  const weekdays: string[] = [];
  for (let i = 1; i <= 28 && (saturdays.length < 3 || weekdays.length < 5); i++) {
    const day = new Date(Date.now() + i * 86_400_000);
    const dow = day.getDay();
    const iso = day.toISOString().slice(0, 10);
    if (dow === 6 && saturdays.length < 3) saturdays.push(iso);
    else if (dow !== 0 && dow !== 6 && weekdays.length < 5) weekdays.push(iso);
  }
  return { saturdays, weekdays };
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
  const { saturdays, weekdays } = upcomingDates();
  const [date, setDate] = useState(saturdays[0]);
  const [showWeekdays, setShowWeekdays] = useState(false);
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
        <p className="muted">
          Your Tune-Up takes about one day. Saturday is our dedicated Tune-Up day — pick the
          Saturday that works for you.
        </p>

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
        <label>Choose a Saturday</label>
        <div className="chips">
          {saturdays.map((d) => (
            <button key={d} className="chip" aria-pressed={date === d} onClick={() => setDate(d)}>
              {fmtDate(d)}
            </button>
          ))}
        </div>
        {!showWeekdays ? (
          <button
            className="btn ghost"
            style={{ marginTop: 10 }}
            onClick={() => setShowWeekdays(true)}
          >
            Saturdays don't work? See weekday options
          </button>
        ) : (
          <>
            <label style={{ marginTop: 12 }}>Weekdays</label>
            <div className="chips">
              {weekdays.map((d) => (
                <button key={d} className="chip" aria-pressed={date === d} onClick={() => setDate(d)}>
                  {fmtDate(d)}
                </button>
              ))}
            </div>
          </>
        )}

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
