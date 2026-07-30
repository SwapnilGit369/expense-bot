const CACHE = 'swapexp-v3';

self.addEventListener('install', e => {
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', e => {
  // POST requests — never intercept, always network
  if(e.request.method !== 'GET'){
    e.respondWith(fetch(e.request));
    return;
  }
  
  // External APIs — always network
  if(e.request.url.includes('supabase') || 
     e.request.url.includes('workers.dev') ||
     e.request.url.includes('groq') ||
     e.request.url.includes('fonts.googleapis')){
    e.respondWith(fetch(e.request));
    return;
  }
  
  // App shell — network first
  e.respondWith(
    fetch(e.request).catch(() => caches.match(e.request))
  );
});
