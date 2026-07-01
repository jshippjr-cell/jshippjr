(function () {
  "use strict";

  var drum = document.getElementById("rg-drum");
  if (!drum) return;

  var cards = Array.prototype.slice.call(drum.querySelectorAll(".rg-card"));
  var n = cards.length;
  if (!n) return;

  // Radius derived from the actual measured card width, not hardcoded — so
  // the ring still looks right (cards edge-adjacent with a little breathing
  // room) whatever the number of tracks/cases happens to be. Standard
  // "N regular tiles around a circle" formula: half-width / tan(pi/N).
  var cardWidth = cards[0].getBoundingClientRect().width || 320;
  var radius = (cardWidth / (2 * Math.tan(Math.PI / n))) * 1.35;
  drum.style.setProperty("--radius", radius.toFixed(1) + "px");

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  // Real pointer device (mouse/trackpad) vs. touch — decides which
  // interaction model runs below: auto-spin + scroll-to-speed-up on
  // desktop, or drag-to-rotate on touch. Never both.
  var isDesktop = window.matchMedia("(hover: hover) and (pointer: fine)").matches;

  var rotation = 0;
  var velocity = 0;
  var dragging = false;
  var lastX = 0;
  var moved = 0;
  var momentumId = null;

  // Every motion mode below shares this one element: instant 1:1 drag,
  // instant per-frame momentum/auto-rotate physics, and an eased "snap to
  // front" on click — the first two want NO css transition (they already
  // are the animation, frame by frame); only the click-triggered snap wants
  // an eased transition.
  function setTransition(on) {
    drum.style.transition = on ? "transform .6s cubic-bezier(.2,.8,.2,1)" : "none";
  }

  function apply() {
    drum.style.transform = "rotateY(" + rotation.toFixed(3) + "deg)";
  }

  function stopMomentum() {
    if (momentumId) {
      cancelAnimationFrame(momentumId);
      momentumId = null;
    }
  }

  function momentumStep() {
    rotation += velocity;
    velocity *= 0.94;
    apply();
    if (Math.abs(velocity) > 0.01) {
      momentumId = requestAnimationFrame(momentumStep);
    } else {
      momentumId = null;
    }
  }

  // ------------------------------------------------------------------ //
  // Touch: drag-to-rotate + release momentum. All functions below are
  // still declared unconditionally (harmless if unused) so spinToFront can
  // safely call stopMomentum() regardless of which mode is actually live —
  // only the pointerdown listener that drives them is gated by isDesktop.
  // ------------------------------------------------------------------ //

  // Deliberately NOT using setPointerCapture here: capturing the pointer on
  // the drum redirects pointerup's target to the drum itself, and the click
  // event synthesized right after inherits that same (wrong) target — so
  // every non-drag click on a card silently lands on the drum <div> instead
  // of the card <a>, and never navigates. Plain window-level move/up
  // listeners (attached only while dragging) avoid that pitfall entirely —
  // pointerup keeps its natural target, so a real click resolves normally.
  //
  // pointermove can fire far more often than the display repaints (some
  // trackpads/mice report well past 60Hz) — writing a style + forcing a
  // layout on EVERY event, rather than once per animation frame, is what
  // made the drag feel janky. A raw dx is only recorded here; a single
  // rAF tick per frame coalesces however many events landed and applies
  // ONE transform write, matched to the actual render cadence.
  var frameQueued = false;
  var frameId = null;
  var frameX = 0;
  var frameT = 0;

  function onMove(e) {
    if (!dragging) return;
    moved += Math.abs(e.clientX - lastX);
    lastX = e.clientX;
    if (!frameQueued) {
      frameQueued = true;
      frameId = requestAnimationFrame(applyDragFrame);
    }
  }

  // NOT gated on `dragging` — a real regression lived here: for a short/quick
  // drag, pointerup (which sets dragging=false) frequently beats the queued
  // rAF callback, so bailing here silently dropped the final bit of motion
  // and its velocity, reading as the drag "not responding." lastX/frameX
  // stay meaningful even after release, so it's always safe to flush them.
  function applyDragFrame() {
    frameQueued = false;
    frameId = null;
    var now = performance.now();
    var dt = Math.max(1, now - frameT);
    var dx = lastX - frameX;
    var delta = dx * 0.3;
    rotation += delta;
    velocity = delta * (16 / dt); // normalize to a ~60fps-per-frame step
    frameX = lastX;
    frameT = now;
    apply();
  }

  function onUp() {
    if (!dragging) return;
    dragging = false;
    drum.classList.remove("rg-dragging");
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
    window.removeEventListener("pointercancel", onUp);
    // Flush any motion still waiting on a queued rAF right now, rather than
    // hoping that frame arrives before this function returns — release must
    // never lose the last bit of drag or compute momentum off a stale
    // velocity. Cancel the pending frame first: if it were left to fire on
    // its own next, it would recompute dx as 0 (frameX already caught up
    // here) and stomp the just-flushed velocity back to 0, killing momentum
    // a tick after it started.
    if (frameQueued) {
      cancelAnimationFrame(frameId);
      applyDragFrame();
    }
    // The drag itself is direct, user-driven motion (1:1 with the pointer) —
    // only the momentum continuation afterward is "automatic," so that's
    // the one piece reduced-motion turns off; the rotation just stops where
    // the pointer released it instead of coasting on.
    if (!reduceMotion && Math.abs(velocity) > 0.05) momentumStep();
  }

  function onDown(e) {
    if (typeof e.button === "number" && e.button !== 0) return;
    stopMomentum();
    setTransition(false);
    dragging = true;
    moved = 0;
    lastX = e.clientX;
    frameX = e.clientX;
    frameT = performance.now();
    drum.classList.add("rg-dragging");
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
  }

  // ------------------------------------------------------------------ //
  // Desktop: the drum spins on its own at a steady idle rate, and
  // scrolling over the stage gives it a temporary speed boost that decays
  // back down. Replaces drag entirely on a real pointer device.
  // ------------------------------------------------------------------ //
  var BASE_SPEED = 6; // degrees per second at idle
  var boost = 0;
  var autoRotateId = null;
  var lastAutoT = null;

  function autoRotateStep(t) {
    if (lastAutoT == null) lastAutoT = t;
    var dt = (t - lastAutoT) / 1000;
    lastAutoT = t;
    boost *= Math.pow(0.9, dt * 60); // frame-rate-independent decay toward 0
    rotation += (BASE_SPEED + boost) * dt;
    apply();
    autoRotateId = requestAnimationFrame(autoRotateStep);
  }

  function startAutoRotate() {
    if (autoRotateId || reduceMotion) return;
    lastAutoT = null;
    setTransition(false);
    autoRotateId = requestAnimationFrame(autoRotateStep);
  }

  function stopAutoRotate() {
    if (autoRotateId) {
      cancelAnimationFrame(autoRotateId);
      autoRotateId = null;
    }
  }

  // A card popping forward parks the drum facing it — ambient motion (of
  // either kind) pauses until the card is deactivated again.
  function pauseAmbientMotion() {
    stopMomentum();
    stopAutoRotate();
  }

  if (isDesktop) {
    startAutoRotate();
    drum.addEventListener("wheel", function (e) {
      if (!autoRotateId) return; // paused while a card is active — scroll does nothing
      boost += Math.min(Math.abs(e.deltaY), 120) * 0.6;
    }, { passive: true });
  } else {
    drum.addEventListener("pointerdown", onDown);
  }
  setTransition(false);
  apply();

  // ------------------------------------------------------------------ //
  // Track playback: clicking a track card pops it forward, highlights it,
  // spins the drum to face it front-on, and plays its audio through the
  // docked player (styling reused verbatim from /showreel). Case-study
  // cards have no audio and keep their normal navigation behavior.
  // ------------------------------------------------------------------ //
  var player = document.querySelector("[data-rg-player]");
  var audio = document.querySelector("[data-rg-audio]");
  var titleEl = document.querySelector("[data-rg-title]");
  var scrub = document.querySelector("[data-rg-scrub]");
  var toggleBtn = document.querySelector("[data-rg-toggle]");
  var prevBtn = document.querySelector("[data-rg-prev]");
  var nextBtn = document.querySelector("[data-rg-next]");

  var trackCards = cards.filter(function (c) { return !!c.dataset.audioUrl; });
  var activeCard = null;

  // The shortest rotation that brings this card's slot to face the viewer —
  // shifted by whatever multiple of 360 lands closest to the CURRENT
  // rotation, so clicking never spins the drum the long way round.
  function angleToFront(slotAngle) {
    var target = -slotAngle;
    var k = Math.round((rotation - target) / 360);
    return target + k * 360;
  }

  function spinToFront(card) {
    var slot = parseFloat(card.style.getPropertyValue("--slot-angle")) || 0;
    pauseAmbientMotion();
    rotation = angleToFront(slot);
    setTransition(true);
    apply();
    window.setTimeout(function () { setTransition(false); }, 650);
  }

  function setActiveCard(card) {
    if (activeCard) activeCard.classList.remove("rg-active");
    activeCard = card;
    card.classList.add("rg-active");
    drum.classList.add("rg-has-active");
  }

  function setPlayingUI(on) {
    if (toggleBtn) toggleBtn.classList.toggle("is-playing", on);
  }

  // `reveal` defaults to true (a real click: pop the card forward, spin it to
  // front, show the docked player). The entrance's own ambient loop passes
  // reveal:false — it plays quietly in the background with no card popped
  // and no player shown, until the visitor actually clicks something.
  function loadTrack(card, autoplay, reveal) {
    if (!audio || !card || !card.dataset.audioUrl) return;
    if (reveal !== false) {
      setActiveCard(card);
      spinToFront(card);
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

  // Clicking the currently-active card a SECOND time closes it back down:
  // un-pop/un-highlight it (the card "goes back into the carousel"), hide
  // the docked player, resume the default entrance track quietly in the
  // background, and let the drum resume spinning on its own (desktop only —
  // on touch, motion is drag-driven only, same as before).
  function deactivate() {
    if (activeCard) activeCard.classList.remove("rg-active");
    activeCard = null;
    drum.classList.remove("rg-has-active");
    if (player) player.classList.remove("on");
    if (trackCards.length) loadTrack(trackCards[0], true, false);
    else if (audio) audio.pause();
    if (isDesktop) startAutoRotate();
  }

  function step(dir) {
    if (!trackCards.length) return;
    var i = activeCard ? trackCards.indexOf(activeCard) : -1;
    i = i < 0 ? 0 : (i + dir + trackCards.length) % trackCards.length;
    loadTrack(trackCards[i], true);
  }

  cards.forEach(function (card) {
    card.addEventListener("click", function (e) {
      if (moved > 6) { e.preventDefault(); return; } // a real drag, not a click
      if (!card.dataset.audioUrl) return; // a case card: let it navigate normally
      e.preventDefault();
      if (card === activeCard) deactivate();
      else loadTrack(card, true);
    });
  });

  // ------------------------------------------------------------------ //
  // Holographic tilt: each card tips toward the cursor and shows a soft
  // cursor-tracked sheen, independent of (and layered on top of) whatever
  // slot/active/dimmed transform already applies. Real pointer devices
  // only — touch has no hover to drive this from, and gating it out there
  // avoids a tilt that gets "stuck" with no mouseleave to reset it.
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
        var tiltX = ((rect.height / 2 - y) / rect.height) * 16;
        var tiltY = ((x - rect.width / 2) / rect.width) * 16;
        card.style.setProperty("--tilt-x", tiltX.toFixed(2) + "deg");
        card.style.setProperty("--tilt-y", tiltY.toFixed(2) + "deg");
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

  // The intro gate's "with sound" choice IS the user gesture that satisfies
  // the browser's autoplay policy — start the first track (index 0, already
  // Chordential's chosen "Strings Arrangement..." track) looping quietly in
  // the background. reveal:false — no card pops, no player shows, until the
  // visitor actually clicks a card themselves.
  document.addEventListener("chordential:entered", function (e) {
    if (e.detail && e.detail.sound && trackCards.length) {
      loadTrack(trackCards[0], true, false);
    }
  });
})();
