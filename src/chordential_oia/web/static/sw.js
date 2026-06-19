/* Chordential service worker — native Web Push for the installed PWA.
 * Served from the site root (/sw.js) so its scope covers the whole app.
 * On a push it shows an OS notification; tapping it opens/focuses the
 * dashboard at the notification's deep-link (default: the Signal Radar). */

self.addEventListener('install', function (event) {
  self.skipWaiting();
});

self.addEventListener('activate', function (event) {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('push', function (event) {
  var data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = {}; }
  var title = data.title || 'New gig on Chordential';
  var options = {
    body: data.body || '',
    icon: '/static/icon-192.png',
    badge: '/static/icon-192.png',
    tag: data.tag || 'chordential-gig',
    renotify: true,
    data: { url: data.url || '/signals' }
  };
  // Stamp the home-screen app icon with a red count badge (iOS 16.4+ / desktop).
  // Floor at 1 so a test alert (which may find 0 unactioned gigs) still badges.
  var count = (typeof data.count === 'number' && data.count > 0) ? data.count : 1;
  var work = [self.registration.showNotification(title, options)];
  if (self.navigator && self.navigator.setAppBadge) {
    work.push(self.navigator.setAppBadge(count).catch(function () {}));
  }
  event.waitUntil(Promise.all(work));
});

self.addEventListener('notificationclick', function (event) {
  event.notification.close();
  // Opening the app from the alert clears the icon badge.
  if (self.navigator && self.navigator.clearAppBadge) {
    self.navigator.clearAppBadge().catch(function () {});
  }
  var target = (event.notification.data && event.notification.data.url) || '/signals';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (clients) {
      for (var i = 0; i < clients.length; i++) {
        var c = clients[i];
        if ('focus' in c) {
          c.navigate(target);
          return c.focus();
        }
      }
      if (self.clients.openWindow) return self.clients.openWindow(target);
    })
  );
});
