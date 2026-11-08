const OFFLINE_CACHE = "suhaeng-math-offline-v1";
const OFFLINE_PAGE = "/offline.html";

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(OFFLINE_CACHE).then((cache) => cache.add(OFFLINE_PAGE)));
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter((name) =>
      name.startsWith("suhaeng-math-offline-") && name !== OFFLINE_CACHE,
    ).map((name) => caches.delete(name)));
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.mode !== "navigate" || request.method !== "GET" ||
      new URL(request.url).origin !== self.location.origin) return;

  event.respondWith(fetch(request).catch(async () => {
    return (await caches.match(OFFLINE_PAGE, { cacheName: OFFLINE_CACHE })) ?? Response.error();
  }));
});
