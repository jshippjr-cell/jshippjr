/* Chordential UI layer — progressive enhancement only (ux-build-spec.md).
   Every screen works fully without this file. Binds by data-* attributes:
     [data-arrive]     — children stagger in on first view (40ms, 300ms cap)
     [data-drawer-src] — open link's target in a right-side drawer
     [data-qstack]     — review-queue focus stack + j/k/Enter keys (step 8)
   Honors prefers-reduced-motion (CSS collapses durations; we also skip class churn). */
(function () {
  'use strict';
  var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---- content arrivals (§2.11): things move into place, chrome pre-exists ---- */
  function initArrive() {
    var containers = document.querySelectorAll('[data-arrive]');
    if (!containers.length) return;
    if (reduced || !('IntersectionObserver' in window)) {
      containers.forEach(function (c) {
        c.querySelectorAll('.arrive').forEach(function (k) { k.classList.add('in'); });
      });
      return;
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        var kids = e.target.querySelectorAll('.arrive');
        var step = Math.min(40, 300 / Math.max(kids.length, 1));
        kids.forEach(function (k, i) {
          setTimeout(function () { k.classList.add('in'); }, i * step);
        });
        io.unobserve(e.target);
      });
    }, { rootMargin: '0px 0px -5% 0px' });
    containers.forEach(function (c) {
      // mark direct children unless the template marked specific ones
      if (!c.querySelector('.arrive')) {
        Array.prototype.forEach.call(c.children, function (k) { k.classList.add('arrive'); });
      }
      io.observe(c);
    });
  }

  /* The eased hairline that crept toward 90% while a request was in flight lived
     here. It was removed, not fixed: the width was a decay curve on a timer with
     no connection to the work, on the one form that also runs the thinking veil —
     so the page claimed determinate progress it could not know, three loading
     states deep. The Living OS rule is that motion reports real state. The
     .progress-hairline CSS stays for a transfer that can report real bytes (the
     client portal's upload already drives one from XHR progress events). */

  /* ---- drawer (§2.3): act on an entity without leaving it ---- */
  var drawerEls = null, drawerTrigger = null;

  function ensureDrawer() {
    if (drawerEls) return drawerEls;
    var backdrop = document.createElement('div');
    backdrop.className = 'drawer-backdrop';
    var panel = document.createElement('aside');
    panel.className = 'drawer';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-modal', 'true');
    panel.setAttribute('inert', '');
    document.body.appendChild(backdrop);
    document.body.appendChild(panel);
    backdrop.addEventListener('click', closeDrawer);
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && panel.classList.contains('open')) closeDrawer();
    });
    drawerEls = { backdrop: backdrop, panel: panel };
    return drawerEls;
  }

  function closeDrawer() {
    if (!drawerEls) return;
    drawerEls.panel.classList.add('closing');
    drawerEls.panel.classList.remove('open');
    drawerEls.backdrop.classList.remove('open');
    drawerEls.panel.setAttribute('inert', '');
    setTimeout(function () { drawerEls.panel.classList.remove('closing'); }, 400);
    if (drawerTrigger && drawerTrigger.focus) drawerTrigger.focus();
    drawerTrigger = null;
  }

  function openDrawer(url, trigger) {
    var els = ensureDrawer();
    drawerTrigger = trigger || null;
    els.panel.innerHTML = '<button class="drawer-close" aria-label="Close">✕</button>' +
                          '<div class="drawer-body muted small">Loading…</div>';
    els.panel.querySelector('.drawer-close').addEventListener('click', closeDrawer);
    els.panel.removeAttribute('inert');
    els.panel.classList.add('open');
    els.backdrop.classList.add('open');
    fetch(url, { headers: { 'X-Requested-With': 'drawer' } })
      .then(function (r) { return r.text(); })
      .then(function (html) {
        var doc = new DOMParser().parseFromString(html, 'text/html');
        var content = doc.querySelector('.content') || doc.querySelector('main') || doc.body;
        var body = els.panel.querySelector('.drawer-body');
        body.classList.remove('muted', 'small');
        body.innerHTML = '';
        body.appendChild(content);
        // re-run the enhancements the page load would have applied
        stampTimezones(body);
        var h = body.querySelector('.topbar-title, h1');
        if (h && h.focus) { h.setAttribute('tabindex', '-1'); h.focus(); }
      })
      .catch(function () { window.location.href = url; }); // graceful fallback
  }

  /* the base-page timezone enhancement, re-runnable for injected content */
  function stampTimezones(root) {
    root.querySelectorAll('form.js-localtime input[name="tz_offset"]').forEach(function (h) {
      h.value = String(new Date().getTimezoneOffset());
    });
    function loc(sel, fmt) {
      root.querySelectorAll(sel).forEach(function (el) {
        var iso = el.getAttribute('data-utc') || el.getAttribute('data-utc-date')
                || el.getAttribute('data-utc-time');
        if (!iso) return;
        var d = new Date(iso);
        if (!isNaN(d)) el.textContent = fmt(d);
      });
    }
    loc('time[data-utc]', function (d) {
      return d.toLocaleString([], { weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    });
    loc('time[data-utc-date]', function (d) {
      return d.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
    });
    loc('time[data-utc-time]', function (d) {
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    });
  }

  function initDrawerLinks() {
    document.addEventListener('click', function (e) {
      var a = e.target.closest && e.target.closest('[data-drawer-src]');
      if (!a) return;
      // let modified clicks (new tab etc.) behave normally
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
      e.preventDefault();
      openDrawer(a.getAttribute('data-drawer-src') || a.getAttribute('href'), a);
    });
  }

  /* ---- view switch (§2.4): same data, two representations ---- */
  function initViewSwitch() {
    document.querySelectorAll('[data-viewswitch]').forEach(function (sw) {
      var key = 'chordential.view.' + sw.getAttribute('data-viewswitch');
      var panes = document.querySelectorAll('.view-pane[data-viewname]');
      var btns = sw.querySelectorAll('button[data-view]');
      function show(name, save) {
        btns.forEach(function (b) { b.classList.toggle('active', b.getAttribute('data-view') === name); });
        panes.forEach(function (p) {
          var on = p.getAttribute('data-viewname') === name;
          if (on) { p.removeAttribute('hidden'); } else { p.setAttribute('hidden', ''); }
        });
        if (save) { try { localStorage.setItem(key, name); } catch (e) {} }
      }
      btns.forEach(function (b) {
        b.addEventListener('click', function () { show(b.getAttribute('data-view'), true); });
      });
      var saved = null;
      try { saved = localStorage.getItem(key); } catch (e) {}
      if (saved && sw.querySelector('button[data-view="' + saved + '"]')) show(saved, false);
    });
  }

  /* ---- queue keyboard (§2.5 adapted): j/k navigate, Enter = the row's primary ---- */
  function initQstack() {
    var table = document.querySelector('[data-qstack]');
    if (!table) return;
    var rows = Array.prototype.slice.call(table.querySelectorAll('tbody tr'));
    if (!rows.length) return;
    var pos = -1;
    function focusRow(i) {
      if (pos >= 0 && rows[pos]) rows[pos].classList.remove('q-focus');
      pos = Math.max(0, Math.min(rows.length - 1, i));
      rows[pos].classList.add('q-focus');
      rows[pos].scrollIntoView({ block: 'nearest', behavior: reduced ? 'auto' : 'smooth' });
    }
    document.addEventListener('keydown', function (e) {
      var t = e.target;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return;
      if (e.key === 'j') { focusRow(pos + 1); }
      else if (e.key === 'k') { focusRow(pos - 1); }
      else if (e.key === 'Enter' && pos >= 0) {
        var btn = rows[pos].querySelector('.btn.primary, .btn-live');
        if (btn) { e.preventDefault(); btn.click(); }
      }
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    initArrive();
    initDrawerLinks();
    initViewSwitch();
    initQstack();
  });
})();
