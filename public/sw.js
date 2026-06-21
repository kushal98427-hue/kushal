// Minimal service worker — makes the app installable as a PWA.
// Offline caching is deliberately out of scope for v0.1; we'll add a smart
// cache strategy once we know which routes shopkeepers actually use.

self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", () => {
  // Pass through to network — no caching yet.
});
