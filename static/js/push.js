/* Dashboard push-notification opt-in.
 *
 * Opt-in is per device: the toggle reflects THIS browser's subscription, not
 * an account-wide preference. gaamosPush() is the Alpine component behind the
 * button on the Orders screen.
 */
(function () {
  function urlBase64ToUint8Array(base64String) {
    // VAPID keys travel as base64url; PushManager wants raw bytes.
    const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    const raw = atob(base64);
    return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
  }

  function bufToBase64Url(buf) {
    const bytes = new Uint8Array(buf);
    let s = "";
    for (const b of bytes) s += String.fromCharCode(b);
    return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }

  // True when this subscription was created against a different server key than
  // the one we now serve — i.e. the keypair was rotated. Such a subscription can
  // never receive again (the push service 403s our signature), so it must be
  // replaced rather than reused.
  function isStale(sub, vapidKey) {
    const key = sub.options && sub.options.applicationServerKey;
    if (!key) return false; // browser won't tell us; leave it alone
    return bufToBase64Url(key) !== vapidKey;
  }

  function post(url, body) {
    const m = document.cookie.match("(^|;)\\s*csrftoken\\s*=\\s*([^;]+)");
    return fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": m ? decodeURIComponent(m[2]) : "",
      },
      body: JSON.stringify(body),
    });
  }

  window.gaamosPush = function (vapidKey) {
    return {
      // 'unsupported' | 'blocked' | 'off' | 'on' | 'busy'
      state: "busy",
      supported: false,

      async init() {
        this.supported =
          "serviceWorker" in navigator &&
          "PushManager" in window &&
          "Notification" in window &&
          !!vapidKey;
        if (!this.supported) {
          this.state = "unsupported";
          return;
        }
        if (Notification.permission === "denied") {
          this.state = "blocked";
          return;
        }
        const reg = await navigator.serviceWorker.ready;
        const sub = await reg.pushManager.getSubscription();
        if (sub && isStale(sub, vapidKey)) {
          // Keys were rotated server-side. Re-register silently so the operator
          // never has to know it happened; without this the device stays
          // subscribed to a key nobody signs with any more and goes quiet
          // forever.
          console.info("push: server key changed, re-registering");
          this.state = "busy";
          try {
            await post("/dashboard/push/unsubscribe/", { endpoint: sub.endpoint });
            await sub.unsubscribe();
          } catch (e) {
            console.warn("push: could not clear stale subscription", e);
          }
          return this.enable();
        }
        this.state = sub ? "on" : "off";
      },

      get label() {
        return {
          unsupported: "Not supported on this device",
          blocked: "Blocked in browser settings",
          off: "Turn on notifications",
          on: "Notifications on — tap to turn off",
          busy: "Working…",
        }[this.state];
      },

      async toggle() {
        if (this.state === "on") return this.disable();
        if (this.state === "off") return this.enable();
      },

      async enable() {
        this.state = "busy";
        try {
          const perm = await Notification.requestPermission();
          if (perm !== "granted") {
            this.state = perm === "denied" ? "blocked" : "off";
            return;
          }
          const reg = await navigator.serviceWorker.ready;
          // Reuse an existing subscription — resubscribing the same browser
          // would otherwise churn the endpoint on every toggle. But only if it
          // was made against the key we still sign with.
          let existing = await reg.pushManager.getSubscription();
          if (existing && isStale(existing, vapidKey)) {
            await existing.unsubscribe();
            existing = null;
          }
          const sub =
            existing ||
            (await reg.pushManager.subscribe({
              userVisibleOnly: true,
              applicationServerKey: urlBase64ToUint8Array(vapidKey),
            }));
          const r = await post("/dashboard/push/subscribe/", sub.toJSON());
          this.state = r.ok ? "on" : "off";
        } catch (e) {
          console.error("push enable failed", e);
          this.state = "off";
        }
      },

      async disable() {
        this.state = "busy";
        try {
          const reg = await navigator.serviceWorker.ready;
          const sub = await reg.pushManager.getSubscription();
          if (sub) {
            // Tell the server first: if unsubscribe() succeeds but the POST
            // fails, the server keeps sending to a dead endpoint until the
            // push service 410s it away.
            await post("/dashboard/push/unsubscribe/", { endpoint: sub.endpoint });
            await sub.unsubscribe();
          }
          this.state = "off";
        } catch (e) {
          console.error("push disable failed", e);
          this.state = "on";
        }
      },
    };
  };
})();
