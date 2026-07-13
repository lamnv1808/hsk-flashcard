
const CACHE='hsk-flashcards-v23';
const ASSETS=[
  './','index.html','styles.css','app.js','data.js','manifest.webmanifest',
  'core/auth/auth-context-query.js','core/sessions/study-session-engine.js',
  'core/util/date.js','core/util/levels.js','core/util/shuffle.js','core/util/card-index.js',
  'core/content/content-pack.js','packs/hsk/hsk-content-pack.js',
  'core/cards/card-repository.js','core/settings/settings-repository.js',
  'core/progress/progress-repository.js','core/progress/progress-writer.js',
  'core/sessions/study-session-query.js','core/analytics/analytics-query.js',
  'core/metadata/user-metadata-query.js','core/testing/test-mode-query.js',
  'supabase-config.js','auth.js','sync.js','test.js','metadata.js','insights.js',
  'icons/icon-192.png','icons/icon-512.png','icons/icon-maskable-512.png',
  'icons/apple-touch-icon-180.png','icons/favicon-32.png'
];
self.addEventListener('install',e=>{self.skipWaiting();e.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS)))});
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k))))));
self.addEventListener('fetch',e=>{
  // Only handle same-origin GETs. Auth/sync calls (cross-origin, POST) pass straight to the network.
  if(e.request.method!=='GET') return;
  if(new URL(e.request.url).origin!==self.location.origin) return;
  e.respondWith(
    caches.match(e.request).then(r=>r||fetch(e.request).catch(()=>{
      // Offline fallback: serve the cached app shell for navigations.
      if(e.request.mode==='navigate') return caches.match('index.html');
      return Response.error();
    }))
  );
});
