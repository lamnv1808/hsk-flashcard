
const CACHE='hsk-flashcards-v4';
const ASSETS=[
  './','index.html','styles.css','app.js','data.js','manifest.webmanifest',
  'icons/icon-192.png','icons/icon-512.png','icons/icon-maskable-512.png',
  'icons/apple-touch-icon-180.png','icons/favicon-32.png'
];
self.addEventListener('install',e=>{self.skipWaiting();e.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS)))});
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k))))));
self.addEventListener('fetch',e=>{
  e.respondWith(
    caches.match(e.request).then(r=>r||fetch(e.request).catch(()=>{
      // Offline fallback: serve the cached app shell for navigations.
      if(e.request.mode==='navigate') return caches.match('index.html');
      return Response.error();
    }))
  );
});
