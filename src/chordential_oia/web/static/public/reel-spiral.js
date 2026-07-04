/* The Reel — spiral stream (translated from the pacomepertant.com teardown,
 * docs/design/ux-teardown-pacomepertant.md §"Home (spiral)").
 *
 * Geometry: every card sits on a helix. One "travel" parameter t (in card
 * units) is integrated per frame from scroll/drag velocity, and each card's
 * wrapped offset u = wrap(i - t) maps to a 3D pose: an arc in x/z (depth)
 * climbing diagonally in y. The focus card (u≈0) is nearest, crisp and
 * full-bright; cards recede into depth blur + dim in both directions —
 * the depth-of-field look, without WebGL: plain CSS 3D transforms written
 * once per rAF.
 *
 * Physics: nothing snaps. Scroll adds velocity; velocity decays; clicking a
 * card eases t toward it (shortest wrap). The lerp IS the animation — cards
 * carry no CSS transform transition in spiral mode (that would rubber-band
 * against per-frame writes).
 *
 * Kept verbatim from the previous carousel: the docked player wiring,
 * click-to-play/deactivate, holographic tilt + sheen, the intro-gate
 * ambient start, and the pure-CSS list fallback (checkbox toggle) — with
 * one addition: entering list mode clears the inline styles this engine
 * writes (CSS alone can't override inline), and leaving it restarts.
 */
(function () {
  "use strict";

  var drum = document.getElementById("rg-drum");
  if (!drum) return;
  var stage = drum.closest(".rg-stage") || drum.parentElement;

  var cards = Array.prototype.slice.call(drum.querySelectorAll(".rg-card"));
  var n = cards.length;
  if (!n) return;

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var isDesktop = window.matchMedia("(hover: hover) and (pointer: fine)").matches;

  drum.classList.add("rg-spiral");

  // ------------------------------------------------------------------ //
  // Geometry — viewport-responsive, recomputed on resize.
  // ------------------------------------------------------------------ //
  var G = {};
  function computeGeometry() {
    var vw = window.innerWidth || 1200;
    var small = vw < 640;
    G.R = small ? Math.max(180, vw * 0.42) : Math.min(vw * 0.30, 430); // helix radius
    G.STEP = 0.52;                    // radians of helix per card
    G.RISE = small ? 46 : 74;         // vertical climb per card (the diagonal)
    G.DRIFT = small ? 14 : 26;        // horizontal drift per card (diagonal lean)
    G.BLUR_PER_U = 1.15;              // px of depth blur per card of distance
    G.BLUR_MAX = 5;
    G.DIM_PER_U = 0.16;               // opacity falloff per card of distance
    G.SCALE_PER_U = 0.045;
  }
  computeGeometry();
  window.addEventListener("resize", computeGeometry);

  // Shortest wrapped offset of card i from travel t: u in [-n/2, n/2) —
  // the stream is endless; browsing loops like the source site's spiral.
  function wrap(u) {
    u = u % n;
    if (u < -n / 2) u += n;
    if (u >= n / 2) u -= n;
    return u;
  }

  var hasActive = false;
  var activeCard = null;

  function layout() {
    for (var i = 0; i < n; i++) {
      var card = cards[i];
      var u = wrap(i - t);
      var phi = u * G.STEP;
      var x = Math.sin(phi) * G.R + u * G.DRIFT;
      var y = -u * G.RISE;
      var z = (Math.cos(phi) - 1) * G.R;   // 0 at focus, receding behind
      var au = Math.abs(u);
      var isActive = card === activeCard;

      var tr = "translate3d(" + x.toFixed(1) + "px," + y.toFixed(1) + "px," + z.toFixed(1) + "px)" +
               " rotateY(" + (-phi * 0.55).toFixed(3) + "rad)" +
               " rotateZ(" + (u * 2.2).toFixed(2) + "deg)" +
               " scale(" + (isActive ? 1.16 : Math.max(0.6, 1 - au * G.SCALE_PER_U)).toFixed(3) + ")" +
               // keep the mouse-driven holographic tilt composable on top
               " rotateX(var(--tilt-x,0deg)) rotateY(var(--tilt-y,0deg))";
      if (isActive) {
        // the picked card pops toward the viewer, front and center
        tr = "translate3d(0px,0px,120px) scale(1.16)" +
             " rotateX(var(--tilt-x,0deg)) rotateY(var(--tilt-y,0deg))";
      }
      card.style.transform = tr;

      var blur = Math.min(au * G.BLUR_PER_U, G.BLUR_MAX);
      var f = blur > 0.15 && !isActive ? "blur(" + blur.toFixed(2) + "px)" : "";
      if (hasActive && !isActive) f += " brightness(.6) saturate(.75)";
      card.style.filter = f || "none";
      card.style.opacity = isActive ? "1" : String(Math.max(0.08, 1 - au * G.DIM_PER_U).toFixed(3));
      card.style.zIndex = isActive ? "40" : String(200 + Math.round(z / 10));
      // far-side cards shouldn't swallow clicks aimed at near ones
      card.style.pointerEvents = au > n / 2 - 0.5 ? "none" : "auto";
    }
  }

  // ------------------------------------------------------------------ //
  // Travel physics — one rAF loop integrates velocity (scroll/drag/idle)
  // and, when a card was clicked, eases t home. The lerp is the animation.
  // ------------------------------------------------------------------ //
  var t = 0;              // travel, in card units
  var velocity = 0;       // cards/second, decays
  var targetT = null;     // set by click — ease toward it, then release
  var IDLE_SPEED = reduceMotion ? 0 : 0.07;  // gentle ambient travel (desktop feel)
  var rafId = null;
  var lastT = null;
  var running = false;

  function tick(now) {
    if (lastT == null) lastT = now;
    var dt = Math.min(0.05, (now - lastT) / 1000);
    lastT = now;

    if (targetT != null) {
      // eased homing (the "spin to front" of the spiral) — pursued, not snapped
      t += (targetT - t) * Math.min(1, dt * 6);
      if (Math.abs(targetT - t) < 0.002) { t = targetT; targetT = null; }
    } else {
      var idle = hasActive ? 0 : IDLE_SPEED;   // park while a card is active
      t += (velocity + idle) * dt;
      velocity *= Math.pow(0.12, dt);          // strong frame-rate-independent decay
      if (Math.abs(velocity) < 0.001) velocity = 0;
    }
    layout();
    rafId = requestAnimationFrame(tick);
  }

  function start() {
    if (running) return;
    running = true;
    lastT = null;
    rafId = requestAnimationFrame(tick);
  }
  function stop() {
    running = false;
    if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
  }

  // Scroll = travel (desktop; passive — the stage never scrolls the page).
  stage.addEventListener("wheel", function (e) {
    if (hasActive) return;              // parked while a track is popped
    targetT = null;
    velocity += e.deltaY * 0.006;
    velocity = Math.max(-6, Math.min(6, velocity));
  }, { passive: true });

  // Drag = travel (touch, and desktop mouse-drag too — it costs nothing).
  var dragging = false, lastX = 0, lastY = 0, moved = 0, lastMoveT = 0;
  function onMove(e) {
    if (!dragging) return;
    var dx = e.clientX - lastX, dy = e.clientY - lastY;
    moved += Math.abs(dx) + Math.abs(dy);
    lastX = e.clientX; lastY = e.clientY;
    var now = performance.now();
    var dt = Math.max(1, now - lastMoveT) / 1000;
    lastMoveT = now;
    // horizontal OR vertical drag both travel the stream (diagonal object)
    var du = -(dx + dy) * 0.0045;
    t += du;
    velocity = reduceMotion ? 0 : du / dt * 0.35;
    targetT = null;
  }
  function onUp() {
    if (!dragging) return;
    dragging = false;
    drum.classList.remove("rg-dragging");
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
    window.removeEventListener("pointercancel", onUp);
  }
  drum.addEventListener("pointerdown", function (e) {
    if (typeof e.button === "number" && e.button !== 0) return;
    if (hasActive) return;
    dragging = true; moved = 0;
    lastX = e.clientX; lastY = e.clientY; lastMoveT = performance.now();
    drum.classList.add("rg-dragging");
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
  });

  // ------------------------------------------------------------------ //
  // Track playback — same contract as before: click pops the card to the
  // focus point and plays it in the docked player; clicking it again puts
  // it back in the stream. Prev/next travel the stream to the neighbor.
  // ------------------------------------------------------------------ //
  var player = document.querySelector("[data-rg-player]");
  var audio = document.querySelector("[data-rg-audio]");
  var titleEl = document.querySelector("[data-rg-title]");
  var scrub = document.querySelector("[data-rg-scrub]");
  var toggleBtn = document.querySelector("[data-rg-toggle]");
  var prevBtn = document.querySelector("[data-rg-prev]");
  var nextBtn = document.querySelector("[data-rg-next]");

  var trackCards = cards.filter(function (c) { return !!c.dataset.audioUrl; });

  function travelToFront(card) {
    var i = cards.indexOf(card);
    // ease along the shortest wrap: target = t + wrap(i - t)
    targetT = t + wrap(i - t);
    velocity = 0;
  }

  function setActiveCard(card) {
    if (activeCard) activeCard.classList.remove("rg-active");
    activeCard = card;
    hasActive = true;
    card.classList.add("rg-active");
    drum.classList.add("rg-has-active");
  }

  function setPlayingUI(on) {
    if (toggleBtn) toggleBtn.classList.toggle("is-playing", on);
  }

  function loadTrack(card, autoplay, reveal) {
    if (!audio || !card || !card.dataset.audioUrl) return;
    if (reveal !== false) {
      setActiveCard(card);
      travelToFront(card);
      if (player) player.classList.add("on");
    }
    if (audio.src !== card.dataset.audioUrl) audio.src = card.dataset.audioUrl;
    if (titleEl) titleEl.textContent = card.dataset.title || "";
    if (autoplay) {
      var p = audio.play();
      if (p && p.catch) p.catch(function () {});
    }
  }

  function togglePlayPause() {
    if (!audio || !audio.src) return;
    if (audio.paused) {
      var p = audio.play();
      if (p && p.catch) p.catch(function () {});
    } else {
      audio.pause();
    }
  }

  function deactivate() {
    if (activeCard) activeCard.classList.remove("rg-active");
    activeCard = null;
    hasActive = false;
    drum.classList.remove("rg-has-active");
    if (player) player.classList.remove("on");
    if (trackCards.length) loadTrack(trackCards[0], true, false);
    else if (audio) audio.pause();
  }

  function step(dir) {
    if (!trackCards.length) return;
    var i = activeCard ? trackCards.indexOf(activeCard) : -1;
    i = i < 0 ? 0 : (i + dir + trackCards.length) % trackCards.length;
    loadTrack(trackCards[i], true);
  }

  cards.forEach(function (card) {
    card.addEventListener("click", function (e) {
      if (moved > 6) { e.preventDefault(); return; }   // that was a drag
      if (!card.dataset.audioUrl) return;              // non-audio: navigate
      e.preventDefault();
      if (card === activeCard) deactivate();
      else loadTrack(card, true);
    });
  });

  // ------------------------------------------------------------------ //
  // Holographic tilt + cursor sheen — unchanged; the tilt vars are read
  // by the inline transform string layout() writes, so they compose.
  // ------------------------------------------------------------------ //
  function resetAllTilts() {
    cards.forEach(function (card) {
      card.style.setProperty("--tilt-x", "0deg");
      card.style.setProperty("--tilt-y", "0deg");
      card.style.setProperty("--hx", "50%");
      card.style.setProperty("--hy", "50%");
      card.classList.remove("rg-tilting");
    });
  }

  if (isDesktop) {
    cards.forEach(function (card) {
      card.addEventListener("mousemove", function (e) {
        var rect = card.getBoundingClientRect();
        var x = e.clientX - rect.left;
        var y = e.clientY - rect.top;
        card.style.setProperty("--tilt-x", (((rect.height / 2 - y) / rect.height) * 16).toFixed(2) + "deg");
        card.style.setProperty("--tilt-y", (((x - rect.width / 2) / rect.width) * 16).toFixed(2) + "deg");
        card.style.setProperty("--hx", ((x / rect.width) * 100).toFixed(1) + "%");
        card.style.setProperty("--hy", ((y / rect.height) * 100).toFixed(1) + "%");
        card.classList.add("rg-tilting");
      });
      card.addEventListener("mouseleave", resetAllTilts);
    });
  }

  if (toggleBtn) toggleBtn.addEventListener("click", function (e) { e.stopPropagation(); togglePlayPause(); });
  if (prevBtn) prevBtn.addEventListener("click", function (e) { e.stopPropagation(); step(-1); });
  if (nextBtn) nextBtn.addEventListener("click", function (e) { e.stopPropagation(); step(1); });

  if (audio) {
    audio.addEventListener("play", function () { setPlayingUI(true); });
    audio.addEventListener("pause", function () { setPlayingUI(false); });
    audio.addEventListener("timeupdate", function () {
      if (scrub && audio.duration) scrub.value = String(Math.round(audio.currentTime / audio.duration * 1000));
    });
    if (scrub) {
      scrub.addEventListener("input", function () {
        if (audio.duration) audio.currentTime = scrub.value / 1000 * audio.duration;
      });
    }
  }

  // ------------------------------------------------------------------ //
  // List-mode toggle: CSS can't beat the inline styles this engine writes,
  // so entering list mode clears them (and stops the loop); leaving it
  // restores the spiral exactly where it was.
  // ------------------------------------------------------------------ //
  var viewToggle = document.getElementById("rg-view-toggle");
  function clearInlineStyles() {
    cards.forEach(function (card) {
      card.style.transform = "";
      card.style.filter = "";
      card.style.opacity = "";
      card.style.zIndex = "";
      card.style.pointerEvents = "";
    });
  }
  if (viewToggle) {
    viewToggle.addEventListener("change", function () {
      if (viewToggle.checked) { stop(); clearInlineStyles(); }
      else { start(); }
    });
    if (viewToggle.checked) clearInlineStyles();
    else { layout(); start(); }
  } else {
    layout();
    start();
  }

  // Intro gate: "with sound" is the autoplay-unlocking gesture — start the
  // first track quietly in the background, nothing popped, no player shown.
  document.addEventListener("chordential:entered", function (e) {
    if (e.detail && e.detail.sound && trackCards.length) {
      loadTrack(trackCards[0], true, false);
    }
  });
})();
