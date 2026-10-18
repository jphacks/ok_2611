export type Coordinates = { latitude: number; longitude: number };
export type LocationFailure = "cancelled" | "unsupported" | "denied" | "timeout" | "unavailable";

// Keeps the user-facing message and adds the reason so screens can avoid re-asking after a denial.
export class LocationError extends Error {
  constructor(public readonly reason: LocationFailure, message: string) {
    super(message);
  }
}

// Coordinates live only for this request. Abort ignores late browser callbacks.
export function getCurrentCoordinates(signal: AbortSignal): Promise<Coordinates> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) { reject(new LocationError("cancelled", "Location request cancelled.")); return; }
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      reject(new LocationError("unsupported", "Location is unavailable in this browser. You can skip to scan a menu."));
      return;
    }
    let settled = false;
    let timer: ReturnType<typeof setTimeout>;
    const finish = (error?: LocationError, coordinates?: Coordinates) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal.removeEventListener("abort", cancel);
      if (error) reject(error);
      else resolve(coordinates!);
    };
    const cancel = () => finish(new LocationError("cancelled", "Location request cancelled."));
    signal.addEventListener("abort", cancel, { once: true });
    timer = setTimeout(() => finish(new LocationError("timeout", "Location took too long. Try again or skip.")), 12_000);
    try {
      navigator.geolocation.getCurrentPosition(
        ({ coords }) => finish(undefined, { latitude: coords.latitude, longitude: coords.longitude }),
        ({ code }) => finish(code === 1
          ? new LocationError("denied", "Location access is denied. Allow it in your browser settings and try again, or skip.")
          : code === 3 ? new LocationError("timeout", "Location took too long. Try again or skip.")
            : new LocationError("unavailable", "Your location is unavailable. Try again or skip.")),
        { enableHighAccuracy: false, timeout: 10_000, maximumAge: 60_000 },
      );
    } catch {
      finish(new LocationError("unsupported", "Location is unavailable. Open this app over HTTPS, or skip."));
    }
  });
}
