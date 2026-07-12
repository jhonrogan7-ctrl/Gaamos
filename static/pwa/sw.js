/* Gaamos service worker.
 * VERSION bump convention: bump on any change to precached asset content,
 * the precache list, or strategy (mirrors the template `asset_v` ?v=
 * cache-buster convention for CSS/JS). Old-version caches are purged on
 * activate.
 *
 * Strategy:
 *   navigations  -> network-first, offline fallback page; HTML never cached
 *   GET /static/ -> stale-while-revalidate (ignoreSearch tolerates ?v=)
 *   anything else (POSTs, /media/, SSE streams, cross-origin) -> untouched
 */
const VERSION = "v2";
const CACHE = `gaamos-shell-${VERSION}`;

const PRECACHE = [
  "/offline/",
  "/static/css/app.css",
  "/static/js/app.js",
  "/static/js/icons.js",
  "/static/pwa/icon-192.png",
  "/static/pwa/icon-512.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(PRECACHE)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;

  if (req.mode === "navigate") {
    e.respondWith(
      fetch(req).catch(() =>
        caches.match("/offline/").then((r) => r || Response.error())
      )
    );
    return;
  }

  const url = new URL(req.url);
  if (req.method === "GET" && url.origin === location.origin && url.pathname.startsWith("/static/")) {
    // Key by pathname only: precache uses bare keys and pages append ?v=
    // cache-busters — one entry per asset, refreshed in place.
    const key = url.origin + url.pathname;
    e.respondWith(
      caches.open(CACHE).then((cache) =>
        cache.match(key, { ignoreSearch: true }).then((cached) => {
          const refresh = fetch(req)
            .then((resp) => {
              if (resp.ok) cache.put(key, resp.clone());
              return resp;
            })
            .catch(() => cached);
          return cached || refresh;
        })
      )
    );
    return;
  }
  // everything else: no respondWith — browser handles it normally
});
