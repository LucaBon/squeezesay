// Service worker minimale per la PWA SqueezeSay.
//
// Strategia: network-first per la pagina (un aggiornamento del server arriva
// subito; la cache serve solo da fallback offline per l'apertura dell'app),
// cache-first per gli asset immutabili (icone, manifest). /command non passa
// mai dalla cache: è il canale comandi verso LMS.
//
// Nota: Chrome registra il service worker solo su HTTPS *fidato* — quindi con
// la CA locale installata (vedi /ca.pem), non con il certificato "accettato
// nonostante l'avviso".
const VERSION = "squeezesay-v3";
const SHELL = ["/", "/manifest.webmanifest", "/icon-192.png", "/icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== self.location.origin) {
    return; // /command (POST) e tutto il resto: sempre rete
  }
  if (url.pathname === "/" || url.pathname === "/index.html") {
    e.respondWith(
      fetch(e.request)
        .then((resp) => {
          const copy = resp.clone();
          caches.open(VERSION).then((c) => c.put("/", copy));
          return resp;
        })
        .catch(() => caches.match("/"))
    );
    return;
  }
  e.respondWith(
    caches.match(e.request).then((hit) => hit || fetch(e.request))
  );
});
