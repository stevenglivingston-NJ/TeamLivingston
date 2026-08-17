/**
 * Phase 5 client-side tracking: Meta Pixel + GA4 gtag.
 *
 * Dedup contract with the Worker: every conversion generates ONE eventId here,
 * fires the browser pixel with it, and forwards it (plus _fbp/_fbc/_ga cookies
 * and the page URL) to the API — the Worker fires the matching CAPI/MP event
 * with the same id, and Meta/GA dedupe the pair. Ad blockers kill the browser
 * half; the server half still lands.
 *
 * The pixel ID is public by nature (it ships in the page). GA4 is optional
 * until the property exists — set VITE_GA4_ID at build time to enable gtag.
 */

const META_PIXEL_ID = "109034988941656"; // KTU Bloomfield NJ (domain verified)
const GA4_ID: string | undefined = import.meta.env.VITE_GA4_ID as string | undefined;

declare global {
  interface Window {
    fbq?: (...args: unknown[]) => void;
    _fbq?: unknown;
    dataLayer?: unknown[];
    gtag?: (...args: unknown[]) => void;
  }
}

/** Inject the Meta Pixel + (optionally) GA4 gtag. Call once from main.tsx. */
export function initTracking(): void {
  if (!window.fbq) {
    const fbq = ((...args: unknown[]) => {
      (fbq as { queue: unknown[] }).queue.push(args);
    }) as ((...args: unknown[]) => void) & { queue: unknown[]; loaded: boolean; version: string };
    fbq.queue = [];
    fbq.loaded = true;
    fbq.version = "2.0";
    window.fbq = fbq;
    window._fbq = fbq;
    const s = document.createElement("script");
    s.async = true;
    s.src = "https://connect.facebook.net/en_US/fbevents.js";
    document.head.appendChild(s);
    window.fbq("init", META_PIXEL_ID);
    window.fbq("track", "PageView");
  }

  if (GA4_ID && !window.gtag) {
    window.dataLayer = window.dataLayer ?? [];
    window.gtag = function gtag() {
      // GA4 reads arguments off dataLayer; must push the Arguments object itself.
      // eslint-disable-next-line prefer-rest-params
      window.dataLayer!.push(arguments);
    };
    window.gtag("js", new Date());
    window.gtag("config", GA4_ID, { send_page_view: true });
    const s = document.createElement("script");
    s.async = true;
    s.src = `https://www.googletagmanager.com/gtag/js?id=${GA4_ID}`;
    document.head.appendChild(s);
  }
}

export function newEventId(): string {
  return crypto.randomUUID();
}

function cookie(name: string): string | undefined {
  const match = document.cookie.match(new RegExp(`(?:^|;\\s*)${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : undefined;
}

/** GA4 client id lives in _ga as GA1.1.<clientId part1>.<part2>. */
function gaClientId(): string | undefined {
  const ga = cookie("_ga");
  const m = ga?.match(/^GA\d+\.\d+\.(.+)$/);
  return m?.[1];
}

export interface TrackingContext {
  eventId: string;
  pageUrl: string;
  fbp?: string;
  fbc?: string;
  gaClientId?: string;
}

/** Fresh context to send with a conversion API call. */
export function trackingContext(eventId: string = newEventId()): TrackingContext {
  return {
    eventId,
    pageUrl: window.location.href,
    fbp: cookie("_fbp"),
    fbc: cookie("_fbc"),
    gaClientId: gaClientId(),
  };
}

/** Fire a browser-pixel event with the dedup eventID. */
export function trackMeta(
  eventName: "Lead" | "InitiateCheckout" | "Purchase",
  eventId: string,
  params?: Record<string, unknown>,
): void {
  window.fbq?.("track", eventName, params ?? {}, { eventID: eventId });
}

/** Fire a GA4 browser event (no-op until VITE_GA4_ID is configured). */
export function trackGa(name: string, params?: Record<string, unknown>): void {
  window.gtag?.("event", name, params ?? {});
}
