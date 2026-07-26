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
          // Existing subscription is reused — resubscribing the same browser
          // would otherwise churn the endpoint on every toggle.
          const sub =
            (await reg.pushManager.getSubscription()) ||
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
