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

  var rotation = 0;
  var velocity = 0;
  var dragging = false;
  var lastX = 0;
  var lastT = 0;
  var moved = 0;
  var momentumId = null;

  // Three motion modes share this one element: instant 1:1 drag, instant
  // per-frame momentum physics, and an eased "snap to front" on click — the
  // first two want NO css transition (they already are the animation, frame
  // by frame); only the click-triggered snap wants an eased transition.
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

  // Deliberately NOT using setPointerCapture here: capturing the pointer on
  // the drum redirects pointerup's target to the drum itself, and the click
  // event synthesized right after inherits that same (wrong) target — so
  // every non-drag click on a card silently lands on the drum <div> instead
  // of the card <a>, and never navigates. Plain window-level move/up
  // listeners (attached only while dragging) avoid that pitfall entirely —
  // pointerup keeps its natural target, so a real click resolves normally.
  function onMove(e) {
    if (!dragging) return;
    var dx = e.clientX - lastX;
    moved += Math.abs(dx);
    var now = performance.now();
    var dt = Math.max(1, now - lastT);
    var delta = dx * 0.3;
    rotation += delta;
    velocity = delta * (16 / dt); // normalize to a ~60fps-per-frame step
    lastX = e.clientX;
    lastT = now;
    apply();
  }

  function onUp() {
    if (!dragging) return;
    dragging = false;
    drum.classList.remove("rg-dragging");
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
    window.removeEventListener("pointercancel", onUp);
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
    lastT = performance.now();
    drum.classList.add("rg-dragging");
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
  }

  drum.addEventListener("pointerdown", onDown);
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
    stopMomentum();
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

  function loadTrack(card, autoplay) {
    if (!audio || !card || !card.dataset.audioUrl) return;
    setActiveCard(card);
    spinToFront(card);
    audio.src = card.dataset.audioUrl;
    if (titleEl) titleEl.textContent = card.dataset.title || "";
    if (player) player.classList.add("on");
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
      if (card === activeCard) togglePlayPause();
      else loadTrack(card, true);
    });
  });

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
  // Chordential's chosen "Strings Arrangement..." track) looping by default.
  document.addEventListener("chordential:entered", function (e) {
    if (e.detail && e.detail.sound && trackCards.length) {
      loadTrack(trackCards[0], true);
    }
  });
})();
