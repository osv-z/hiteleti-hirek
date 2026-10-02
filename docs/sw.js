// Offline működés: az app váza a gyorsítótárból jön, a hírek (JSON) mindig
// először a hálózatról, és csak ha az nem elérhető, a legutóbb mentett változatból.
const ELOTAG = "hiteleti-hirek-";
const VERZIO = ELOTAG + "v1";
const VAZ = ["./", "./index.html", "./manifest.webmanifest", "./icon-192.png", "./icon-512.png", "./apple-touch-icon.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERZIO).then((c) => c.addAll(VAZ)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((kulcsok) => Promise.all(kulcsok.filter((k) => k.startsWith(ELOTAG) && k !== VERZIO).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

async function halozatElobb(keres) {
  const tar = await caches.open(VERZIO);
  try {
    const valasz = await fetch(keres);
    if (valasz.ok) tar.put(keres, valasz.clone());
    return valasz;
  } catch (e) {
    const mentett = await tar.match(keres, { ignoreSearch: true });
    if (mentett) return mentett;
    throw e;
  }
}

async function tarElobb(keres) {
  const tar = await caches.open(VERZIO);
  const mentett = await tar.match(keres);
  const friss = fetch(keres).then((v) => { if (v.ok || v.type === "opaque") tar.put(keres, v.clone()); return v; }).catch(() => null);
  return mentett || (await friss) || Response.error();
}

self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET") return;
  const url = new URL(e.request.url);
  const betutipus = url.hostname === "fonts.googleapis.com" || url.hostname === "fonts.gstatic.com";
  if (url.origin !== location.origin && !betutipus) return;

  if (url.pathname.endsWith(".json") || e.request.mode === "navigate") {
    e.respondWith(halozatElobb(e.request));
  } else {
    e.respondWith(tarElobb(e.request));
  }
});
