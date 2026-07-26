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
const VERSION = "v5";
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

/* --- Web Push: new dashboard orders ------------------------------------- *
 * The server sends a JSON payload; showNotification is mandatory — a push
 * handler that resolves without showing one makes the browser display its own
 * "site updated in background" notice, and repeated offences cost the origin
 * its push permission.
 */
self.addEventListener("push", (e) => {
  let d = {};
  try {
    d = e.data ? e.data.json() : {};
  } catch (_) {
    d = {};
  }
  const title = d.title || "New order";
  e.waitUntil(
    self.registration.showNotification(title, {
      body: d.body || "",
      // Same tag per order => a re-send replaces rather than stacks.
      tag: d.tag || "order",
      renotify: true,
      icon: "/static/pwa/icon-192.png",
      badge: "/static/pwa/icon-192.png",
      data: { url: d.url || "/dashboard/orders/" },
      requireInteraction: false,
    })
  );
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const target = (e.notification.data && e.notification.data.url) || "/dashboard/orders/";
  e.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
      // Reuse an already-open dashboard tab instead of piling up new ones.
      for (const w of wins) {
        if (w.url.includes("/dashboard/") && "focus" in w) {
          w.navigate(target);
          return w.focus();
        }
      }
      return clients.openWindow(target);
    })
  );
});

/* The browser may rotate a push subscription on its own (storage pressure, a
 * key change, browser policy). When it does, the old endpoint stops working and
 * the only notice we get is this event — without handling it the device goes
 * permanently quiet with nothing in the UI to say so.
 */
self.addEventListener("pushsubscriptionchange", (e) => {
  e.waitUntil(
    (async () => {
      try {
        const r = await fetch("/dashboard/push/key/", { credentials: "same-origin" });
        if (!r.ok) return;
        const { key } = await r.json();
        if (!key) return;
        const padding = "=".repeat((4 - (key.length % 4)) % 4);
        const raw = atob((key + padding).replace(/-/g, "+").replace(/_/g, "/"));
        const sub = await self.registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: Uint8Array.from([...raw].map((c) => c.charCodeAt(0))),
        });
        await fetch("/dashboard/push/subscribe/", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(sub.toJSON()),
        });
      } catch (err) {
        // Nothing useful to do here; the page-side check re-registers on the
        // operator's next visit.
      }
    })()
  );
});
