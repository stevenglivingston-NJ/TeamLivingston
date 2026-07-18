import { AWARDS, GALLERY, PHONE_DISPLAY, PHONE_TEL } from "../content";

export function Landing({ onStart }: { onStart: () => void }) {
  return (
    <div className="stage stack">
      <div className="card">
        <div className="awards">
          <span className="medal">🏆</span>
          <span>{AWARDS}</span>
        </div>
        <h1>Get your kitchen's instant price — in minutes.</h1>
        <p>
          Kitchen Tune-Up Bloomfield restores your existing cabinets in about a day. Answer a few
          questions, snap a few photos, and see your firm price on the spot.
        </p>
        <button className="btn" onClick={onStart}>
          Get Your Instant Price
        </button>
        <p className="center muted" style={{ marginTop: 12, marginBottom: 0 }}>
          Prefer to talk?{" "}
          <a href={`tel:${PHONE_TEL}`} style={{ color: "var(--ktu-orange)", fontWeight: 700 }}>
            {PHONE_DISPLAY}
          </a>
        </p>
      </div>

      <div className="card">
        <h2>Real Bloomfield-area results</h2>
        <p className="muted">
          <span className="ba-badge">Before → After</span> — drag-free sliders, real customer
          cabinets.
        </p>
        <div className="gallery">
          {GALLERY.map((g) => (
            <figure key={g.src}>
              <img src={g.src} alt={g.caption} loading="lazy" />
              <figcaption>{g.caption}</figcaption>
            </figure>
          ))}
        </div>
      </div>

      <div className="card center">
        <h2>See your price now</h2>
        <button className="btn" onClick={onStart}>
          Get Your Instant Price
        </button>
      </div>
    </div>
  );
}
