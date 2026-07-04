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

  /* ---- eased hairline progress (§2.8): the number is choreography too ---- */
  window.chordentialEasedProgress = function (el, getTarget, onDone) {
    var bar = el.querySelector('i');
    if (!bar) return;
    if (reduced) { bar.style.width = '100%'; onDone && onDone(); return; }
    var v = 0;
    (function tick() {
      v += (getTarget() - v) * 0.04;
      bar.style.width = v + '%';
      if (v >= 99.5) { bar.style.width = '100%'; onDone && onDone(); return; }
      requestAnimationFrame(tick);
    })();
  };

  /* Forms marked data-progress show the hairline while submitting (analyze, etc.) */
  function initProgressForms() {
    document.querySelectorAll('form[data-progress]').forEach(function (form) {
      form.addEventListener('submit', function () {
        var host = form.querySelector('.progress-hairline');
        if (!host) {
          host = document.createElement('div');
          host.className = 'progress-hairline';
          host.innerHTML = '<i></i>';
          form.appendChild(host);
        }
        host.style.display = 'block';
        var btn = form.querySelector('button[type="submit"]');
        if (btn) { btn.disabled = true; btn.dataset.prevText = btn.textContent; btn.textContent = form.dataset.progress || 'Working…'; }
        // ease toward 90 until the server responds (the page will navigate)
        window.chordentialEasedProgress(host, function () { return 90; });
      });
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    initArrive();
    initProgressForms();
  });
})();
