/* live.js — the Living-OS layer (progressive enhancement only).
 *
 * Philosophy (art-direction bible, "The Living OS principle"): every page
 * carries at least one living element that cannot exist in print, and every
 * motion communicates STATE — the machine thinking, an event arriving, a
 * number becoming true — never decoration. No frameworks; no page requires
 * this file to function. Reduced-motion collapses everything to dignified
 * instant states.
 */
(function () {
  "use strict";
  var reduce = window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var Live = (window.Live = { reduced: reduce });

  /* ---- Live.clock(el): a ticking clock — the cheapest proof the page is
     alive. Blinking colon via CSS (.lv-colon). ---- */
  Live.clock = function (el) {
    function two(n) { return ("0" + n).slice(-2); }
    function tick() {
      var d = new Date();
      el.innerHTML = two(d.getHours()) + '<span class="lv-colon">:</span>' +
        two(d.getMinutes()) + '<span class="lv-colon">:</span>' + two(d.getSeconds());
    }
    tick(); setInterval(tick, 1000);
  };

  /* ---- Live.count(el, to, opts): a number becoming true — eased count-up.
     Honest: only used when the value really changed. ---- */
  Live.count = function (el, to, opts) {
    opts = opts || {};
    var from = opts.from != null ? opts.from : 0;
    var ms = opts.ms || 900, suffix = opts.suffix || "";
    if (reduce) { el.textContent = to + suffix; return; }
    var t0 = performance.now();
    (function step(now) {
      var p = Math.min(1, (now - t0) / ms), e = 1 - Math.pow(1 - p, 3);
      el.textContent = Math.round(from + (to - from) * e) + suffix;
      if (p < 1) requestAnimationFrame(step);
    })(t0);
  };

  /* ---- Live.halo(el): an arrival — the element materializes with a light
     ring. Used when the server reports something CHANGED. ---- */
  Live.halo = function (el) {
    if (reduce || !el) return;
    el.classList.add("lv-halo");
    el.addEventListener("animationend", function h() {
      el.classList.remove("lv-halo"); el.removeEventListener("animationend", h);
    });
  };

  /* ---- Live.think(steps): the machine visibly thinking. Dims the page and
     shows the propagation path while REAL server work runs; resolves when
     done() is called. Never used to fake work (ADR honesty rule). ---- */
  Live.think = function (steps) {
    var veil = document.createElement("div");
    veil.className = "lv-veil";
    veil.innerHTML =
      '<div class="lv-veil-inner">' +
      '<div class="lv-think-dot" aria-hidden="true"></div>' +
      '<div class="lv-think-label">The machine is thinking…</div>' +
      '<div class="lv-path">' + (steps || []).map(function (s) {
        return '<span class="lv-tok">' + s + "</span>";
      }).join('<span class="lv-arr">→</span>') + "</div></div>";
    document.body.appendChild(veil);
    requestAnimationFrame(function () { veil.classList.add("on"); });
    var toks = veil.querySelectorAll(".lv-tok"), i = 0, iv = null;
    if (!reduce && toks.length) {
      iv = setInterval(function () {
        toks[i % toks.length].classList.add("lit"); i++;
      }, 550);
    } else { toks.forEach(function (t) { t.classList.add("lit"); }); }
    return {
      done: function () {
        if (iv) clearInterval(iv);
        veil.classList.remove("on");
        setTimeout(function () { veil.remove(); }, 450);
      }
    };
  };

  /* ---- Live.pulse(fromEl, toEl, cb): an event as light — a comet travels
     between two on-screen elements on a transient overlay canvas. ---- */
  var fx = null, fctx = null, pulses = [], raf = null;
  function ensureFx() {
    if (fx) return;
    fx = document.createElement("canvas");
    fx.className = "lv-fx"; document.body.appendChild(fx);
    fctx = fx.getContext("2d");
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    fx.width = Math.round(window.innerWidth * dpr);
    fx.height = Math.round(window.innerHeight * dpr);
    fctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  function fxLoop(now) {
    fctx.clearRect(0, 0, window.innerWidth, window.innerHeight);
    fctx.globalCompositeOperation = "lighter";
    for (var i = pulses.length - 1; i >= 0; i--) {
      var p = pulses[i], t = Math.min(1, (now - p.t0) / p.dur);
      for (var s = 0; s < 6; s++) {
        var q = Math.max(0, t - s * 0.05), u = 1 - q;
        var x = u * u * p.a[0] + 2 * u * q * p.c[0] + q * q * p.b[0];
        var y = u * u * p.a[1] + 2 * u * q * p.c[1] + q * q * p.b[1];
        var al = (1 - s / 6) * 0.85 * (t > 0.92 ? (1 - t) * 12 : 1);
        var g = fctx.createRadialGradient(x, y, 0, x, y, 14 - s * 1.6);
        g.addColorStop(0, "rgba(228,103,31," + Math.max(0, al) + ")");
        g.addColorStop(1, "rgba(228,103,31,0)");
        fctx.fillStyle = g; fctx.beginPath(); fctx.arc(x, y, 14 - s * 1.6, 0, 7); fctx.fill();
      }
      if (t >= 1) { if (p.cb) p.cb(); pulses.splice(i, 1); }
    }
    fctx.globalCompositeOperation = "source-over";
    if (pulses.length) { raf = requestAnimationFrame(fxLoop); }
    else { raf = null; fx.remove(); fx = null; }
  }
  Live.pulse = function (fromEl, toEl, cb) {
    if (reduce || !fromEl || !toEl) { if (cb) cb(); return; }
    ensureFx();
    var fr = fromEl.getBoundingClientRect(), tr = toEl.getBoundingClientRect();
    var a = [fr.left + fr.width / 2, fr.top + fr.height / 2];
    var b = [tr.left + tr.width / 2, tr.top + tr.height / 2];
    var c = [(a[0] + b[0]) / 2, Math.min(a[1], b[1]) - 60];
    pulses.push({ a: a, b: b, c: c, t0: performance.now(), dur: 750, cb: cb });
    if (!raf) raf = requestAnimationFrame(fxLoop);
  };

  /* ---- auto-wiring ---- */
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-live-clock]").forEach(Live.clock);
    document.querySelectorAll("[data-count-to]").forEach(function (el) {
      var to = parseInt(el.dataset.countTo, 10);
      if (!isNaN(to)) Live.count(el, to, {
        from: parseInt(el.dataset.countFrom || "0", 10),
        suffix: el.dataset.countSuffix || ""
      });
    });
  });
})();

/* ---- The machine thinks (Phase 2): forms marked data-think get the honest
 * thinking experience — the veil runs EXACTLY as long as the real request
 * (council ruling: no minimum-duration padding), the propagation tokens name
 * the real modules (data-think-path), and on return the arrival choreography
 * touches only what the server reports changed (the capture callout + a fit%
 * that actually moved). No JS → the form posts normally, unchanged. ---- */
(function () {
  "use strict";
  var Live = window.Live;
  var KEY_THOUGHT = "lv:thought", KEY_FIT = "lv:fit-before";

  /* A form that spends money or is otherwise irreversible declares data-confirm.
     The guard MUST live here rather than in an inline onsubmit=: this listener is
     capture-phase, so it reaches the event before any handler bound to the form
     itself — an inline confirm() ran only AFTER the fetch below had already sent
     the request, and answering No cancelled nothing but the navigation. The
     data-confirm-skip-when="field=value" escape lets one form ask only for the
     variant that actually spends. */
  function confirmed(form) {
    var msg = form.getAttribute("data-confirm");
    if (!msg) return true;
    var skip = form.getAttribute("data-confirm-skip-when");
    if (skip) {
      var i = skip.indexOf("=");
      var field = i < 0 ? null : form.elements[skip.slice(0, i)];
      if (field && field.value === skip.slice(i + 1)) return true;
    }
    return window.confirm(msg);
  }

  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!form || !form.hasAttribute) return;
    if (form.hasAttribute("data-confirm") && !confirmed(form)) {
      e.preventDefault();
      e.stopPropagation();
      return;                                        // declined: nothing is sent
    }
    if (!form.hasAttribute("data-think")) return;
    if (!window.fetch || !window.FormData) return;   // no-JS/legacy: normal post
    e.preventDefault();
    var path = (form.getAttribute("data-think-path") || "").split("|").filter(Boolean);
    var think = Live.think(path);
    // remember the fit% on screen so the count-up animates only a REAL change
    var fitEl = document.querySelector("[data-fit-pct]");
    if (fitEl) sessionStorage.setItem(KEY_FIT, fitEl.getAttribute("data-fit-pct"));
    sessionStorage.setItem(KEY_THOUGHT, "1");
    fetch(form.action, { method: "POST", body: new FormData(form) })
      .then(function (resp) {
        think.done();
        window.location.href = resp.url ? resp.url + "#intelligence" : window.location.href;
      })
      .catch(function () {           // network hiccup: fall back to the plain post
        think.done();
        sessionStorage.removeItem(KEY_THOUGHT);
        form.removeAttribute("data-think");
        form.submit();
      });
  }, true);

  document.addEventListener("DOMContentLoaded", function () {
    if (sessionStorage.getItem(KEY_THOUGHT) !== "1") return;
    sessionStorage.removeItem(KEY_THOUGHT);
    // halo the ONE thing the server reports changed: the capture callout
    var callout = document.querySelector("#intelligence .callout");
    if (callout) Live.halo(callout);
    // fit% becomes true only if it actually moved
    var fitEl = document.querySelector("[data-fit-pct]");
    var before = parseInt(sessionStorage.getItem(KEY_FIT) || "", 10);
    sessionStorage.removeItem(KEY_FIT);
    if (fitEl && !isNaN(before)) {
      var after = parseInt(fitEl.getAttribute("data-fit-pct"), 10);
      if (!isNaN(after) && after !== before)
        Live.count(fitEl, after, { from: before, ms: 1100, suffix: "%" });
    }
  });
})();

/* ---- Uploads with REAL byte progress (ADR-0038). ------------------------------
 * A form marked data-upload sends over XHR so the operator watches actual bytes
 * move instead of a spinning tab. The console's four uploads — the picture cut,
 * a reference, a deliverable, a new master — carry the largest files in the
 * system (a cut or a stem package is hundreds of MB) and previously had NO
 * feedback at all: a naked multipart POST, a blank tab, and no way to tell a
 * stalled upload from a slow one.
 *
 * Honest liveness, per the Living OS rule: the bar tracks ev.loaded/ev.total and
 * nothing else. There is no indeterminate crawl and no minimum duration — when
 * the browser reports no total (lengthComputable false) we say "Sending…" rather
 * than animate a number we don't have. A failure says so and leaves the file
 * chosen, so the operator retries instead of re-picking.
 *
 * Progressive: no JS, no XHR, or no file chosen → the form posts normally.
 * --------------------------------------------------------------------------- */
(function () {
  "use strict";

  function human(bytes) {
    if (!(bytes >= 0)) return "";
    var mb = bytes / 1048576;
    if (mb >= 1024) return (mb / 1024).toFixed(1) + " GB";
    return mb >= 10 ? Math.round(mb) + " MB" : mb.toFixed(1) + " MB";
  }

  /* The progress element is created on demand so no template has to carry
     markup for a state it may never enter. */
  function rail(form) {
    var el = form.querySelector(".lv-up");
    if (el) return el;
    el = document.createElement("div");
    el.className = "lv-up";
    el.innerHTML = '<div class="lv-up-bar"><i></i></div><span class="lv-up-note"></span>';
    form.appendChild(el);
    return el;
  }

  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!form || !form.hasAttribute || !form.hasAttribute("data-upload")) return;
    /* data-think owns the submit for forms whose wait is the SERVER thinking (the
       AI intake analyze). Two capture-phase handlers both calling preventDefault
       on one submit is a bug waiting to happen, and a veil is the honest signal
       there anyway — the wait is the 10-agent extraction, not the voice memo's
       bytes. Never both; data-think wins. */
    if (form.hasAttribute("data-think")) return;
    var input = form.querySelector('input[type=file]');
    if (!input || !input.files || !input.files.length) return;   // nothing to send
    if (!window.XMLHttpRequest || !window.FormData) return;      // legacy: plain post

    e.preventDefault();
    var btn = form.querySelector('button[type=submit], button:not([type=button])');
    var label = btn ? btn.textContent : "";
    var el = rail(form), fill = el.querySelector("i"), note = el.querySelector(".lv-up-note");
    var total = input.files[0].size || 0;
    el.classList.add("on");
    if (btn) { btn.disabled = true; btn.textContent = "Sending…"; }
    note.textContent = total ? ("0 of " + human(total)) : "Sending…";

    var xhr = new XMLHttpRequest();
    xhr.open("POST", form.action);
    xhr.upload.addEventListener("progress", function (ev) {
      if (!ev.lengthComputable) { note.textContent = "Sending…"; return; }
      var pct = ev.loaded / ev.total;
      fill.style.width = (pct * 100) + "%";
      note.textContent = Math.round(pct * 100) + "% · " +
        human(ev.loaded) + " of " + human(ev.total);
    });
    /* Upload done, server still working (naming, packaging, the ZIP). Say that
       rather than sit at 100% looking hung. */
    xhr.upload.addEventListener("load", function () {
      fill.style.width = "100%";
      note.textContent = "Uploaded — filing it…";
    });
    xhr.addEventListener("load", function () {
      if (xhr.status < 400) { window.location.reload(); return; }
      el.classList.add("failed");
      note.textContent = "Upload failed (" + xhr.status + ") — the file is still chosen, try again";
      if (btn) { btn.disabled = false; btn.textContent = label; }
    });
    xhr.addEventListener("error", function () {
      el.classList.add("failed");
      note.textContent = "Connection lost — the file is still chosen, try again";
      if (btn) { btn.disabled = false; btn.textContent = label; }
    });
    xhr.addEventListener("abort", function () {
      el.classList.remove("on");
      if (btn) { btn.disabled = false; btn.textContent = label; }
    });
    xhr.send(new FormData(form));
  }, true);
})();
