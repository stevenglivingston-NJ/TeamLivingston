import type { Stage } from "../types";

const LABELS: Record<Stage, string> = {
  landing: "Start",
  zip: "Your area",
  details: "Your kitchen",
  photos: "Photos",
  contact: "Your info",
  price: "Your price",
  schedule: "Schedule",
};

export function Progress({
  current,
  total,
  stage,
}: {
  current: number;
  total: number;
  stage: Stage;
}) {
  const pct = Math.round((current / total) * 100);
  return (
    <div className="progress" aria-label={`Step ${current} of ${total}`}>
      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="progress-label">
        Step {current} of {total} — {LABELS[stage]}
      </div>
    </div>
  );
}
