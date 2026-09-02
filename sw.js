// 只做兩件事：讓這頁可以「加到主畫面」當 App 開，以及點通知時把它叫回前景。
// 沒有離線快取——這頁的資料本來就得連線才有意義，快取只會讓人看到舊行情。
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));

self.addEventListener("notificationclick", e => {
  e.notification.close();
  e.waitUntil((async () => {
    const all = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const c of all) {
      if ("focus" in c) return c.focus();
    }
    if (self.clients.openWindow) return self.clients.openWindow("./");
  })());
});
