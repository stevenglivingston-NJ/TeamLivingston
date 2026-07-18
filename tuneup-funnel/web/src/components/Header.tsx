import { PHONE_DISPLAY, PHONE_TEL } from "../content";

export function Header() {
  return (
    <header className="header">
      <div className="brand">
        Kitchen <span>Tune-Up</span>
      </div>
      <a className="call-link" href={`tel:${PHONE_TEL}`} aria-label={`Call us at ${PHONE_DISPLAY}`}>
        📞 {PHONE_DISPLAY}
      </a>
    </header>
  );
}
