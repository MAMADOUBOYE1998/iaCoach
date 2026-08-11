/**
 * Service worker registration.
 *
 * Production only. In dev, Vite serves TypeScript modules on the fly and `/sw.js`
 * is a build output that does not exist — and a worker caching a dev server is a
 * debugging trap, not a feature.
 *
 * Registration failure is logged and swallowed: the worker makes the app work
 * offline, it is not what makes it work.
 */

export function registerServiceWorker(): void {
  if (!import.meta.env.PROD) return;
  if (!("serviceWorker" in navigator)) return;

  // Both the URL and the scope follow the base: on GitHub Pages the app lives at
  // /iaCoach/, and a worker registered at the root would be rejected outright.
  const base = import.meta.env.BASE_URL;

  window.addEventListener("load", () => {
    void navigator.serviceWorker.register(`${base}sw.js`, { scope: base }).catch((error: unknown) => {
      console.warn("Service worker registration failed; the app still works online.", error);
    });
  });
}
