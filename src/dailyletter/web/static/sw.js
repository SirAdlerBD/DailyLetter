// Service worker: shows the notifications the server sends. It caches nothing,
// so the page is always the latest letter.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

self.addEventListener('push', (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (error) {
    data = { body: event.data ? event.data.text() : '' };
  }
  event.waitUntil(self.registration.showNotification(data.title || 'DailyLetter', {
    body: data.body || '',
    tag: data.tag || 'briefje',
    icon: '/static/icon-192.png',
    data: { url: data.url || '/' },
  }));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  // Only pages of this app; a message can never send you elsewhere.
  const target = new URL(event.notification.data && event.notification.data.url || '/', self.location.origin);
  const url = target.origin === self.location.origin ? target.href : self.location.origin + '/';
  event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windows) => {
    for (const win of windows) {
      if (win.url.startsWith(self.location.origin)) return win.focus().then(() => win.navigate(url)).catch(() => win);
    }
    return self.clients.openWindow(url);
  }));
});
