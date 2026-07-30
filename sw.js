const CACHE = 'swapexp-v2';

self.addEventListener('install', e => {
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', e => {
  if(e.request.url.includes('supabase') || 
     e.request.url.includes('groq') || 
     e.request.url.includes('workers.dev') ||
     e.request.url.includes('fonts.googleapis')){
    e.respondWith(fetch(e.request));
    return;
  }
  e.respondWith(
    fetch(e.request).catch(() => caches.match(e.request))
  );
});
