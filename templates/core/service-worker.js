{% load static %}
const CACHE = 'quill-public-v2';
const OFFLINE = '{% static "offline.html" %}';
const ASSETS = [
  OFFLINE,
  '{% static "css/app.css" %}',
  '{% static "js/pwa.js" %}',
  '{% static "icons/quill-192.png" %}',
  '{% static "icons/quill-512.png" %}',
];
const allowed = new Set(ASSETS.map(path => new URL(path, self.location.origin).href));

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(ASSETS)));
});

self.addEventListener('activate', event => {
  event.waitUntil(Promise.all([
    self.clients.claim(),
    caches.keys().then(keys => Promise.all(keys
      .filter(key => key.startsWith('quill-public-') && key !== CACHE)
      .map(key => caches.delete(key)))),
  ]));
});

self.addEventListener('fetch', event => {
  const { request } = event;
  if (request.method !== 'GET' || new URL(request.url).origin !== self.location.origin) return;
  if (request.mode === 'navigate') {
    event.respondWith(fetch(request, { cache: 'no-store' }).catch(async () => {
      const cache = await caches.open(CACHE);
      return await cache.match(OFFLINE) || Response.error();
    }));
  } else if (allowed.has(request.url)) {
    event.respondWith((async () => {
      const cache = await caches.open(CACHE);
      try {
        const response = await fetch(request);
        if (response.ok) await cache.put(request, response.clone());
        return response;
      } catch {
        return await cache.match(request) || Response.error();
      }
    })());
  }
});
