import { useEffect, useRef, useState } from "react";
import type { Action } from "../App";
import type { FunnelState, PhotoSlot } from "../types";

/**
 * Guided in-app camera. Each slot opens the device camera directly via the
 * file-input `capture` attribute (works on iOS/Android without permissions
 * plumbing); desktop falls back to a normal file picker. The angle instruction
 * and required badge are shown per slot; retake replaces the file.
 *
 * Build-spec triggers handled: auto-surface the call-back offer if the user
 * stalls >90s here or fails to add a photo twice.
 */
export function PhotoCapture({
  state,
  dispatch,
  onNext,
  onStall,
}: {
  state: FunnelState;
  dispatch: React.Dispatch<Action>;
  onNext: () => void;
  onStall: () => void;
}) {
  const [photos, setPhotos] = useState<PhotoSlot[]>(state.photos);
  const stalledRef = useRef(false);
  const isDesktop = typeof window !== "undefined" && !/Mobi|Android|iPhone|iPad/i.test(navigator.userAgent);

  // Stall detector: 90s with no required photos captured → offer a call.
  useEffect(() => {
    const timer = setTimeout(() => {
      const anyRequired = photos.some((p) => p.required && p.file);
      if (!anyRequired && !stalledRef.current) {
        stalledRef.current = true;
        onStall();
      }
    }, 90_000);
    return () => clearTimeout(timer);
  }, [photos, onStall]);

  const setSlot = (key: string, file: File) => {
    setPhotos((prev) => {
      const next = prev.map((p) =>
        p.key === key
          ? { ...p, file, previewUrl: URL.createObjectURL(file) }
          : p,
      );
      dispatch({ type: "patch", patch: { photos: next } });
      return next;
    });
  };

  const requiredFilled = photos.filter((p) => p.required && p.file).length;
  const requiredTotal = photos.filter((p) => p.required).length;
  const canContinue = requiredFilled === requiredTotal;

  return (
    <div className="stage stack">
      <div className="card">
        <h1>Add a few photos</h1>
        <p className="muted">
          {requiredTotal} required, {photos.length - requiredTotal} optional. Tap a box to open your
          camera. Tips: lights on, hold the phone level, avoid flash glare.
        </p>
        {isDesktop && (
          <div className="notice" style={{ marginBottom: 12 }}>
            On a computer? You can upload photos here, or text yourself this page's link to finish on
            your phone's camera.
          </div>
        )}
        <div className="slots">
          {photos.map((slot) => (
            <SlotBox key={slot.key} slot={slot} desktop={isDesktop} onFile={(f) => setSlot(slot.key, f)} />
          ))}
        </div>
        <p className="progress-label" style={{ marginTop: 12 }}>
          {requiredFilled} of {requiredTotal} required photos added
        </p>
      </div>

      <button className="btn" disabled={!canContinue} onClick={onNext}>
        {canContinue ? "See my price" : `Add ${requiredTotal - requiredFilled} more required photo(s)`}
      </button>
    </div>
  );
}

function SlotBox({
  slot,
  desktop,
  onFile,
}: {
  slot: PhotoSlot;
  desktop: boolean;
  onFile: (file: File) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const filled = Boolean(slot.previewUrl);

  return (
    <label
      className={`slot ${slot.required ? "required" : ""} ${filled ? "filled" : ""}`}
      onClick={() => inputRef.current?.click()}
    >
      {slot.required && !filled && <span className="req-tag">Required</span>}
      {filled ? (
        <>
          <img src={slot.previewUrl} alt={slot.label} />
          <span className="retake">Retake</span>
        </>
      ) : (
        <>
          <strong>{slot.label}</strong>
          <span>{slot.instruction}</span>
        </>
      )}
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        {...(desktop ? {} : { capture: "environment" })}
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onFile(f);
        }}
      />
    </label>
  );
}
