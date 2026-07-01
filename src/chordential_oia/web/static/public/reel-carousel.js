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
  var cardWidth = cards[0].getBoundingClientRect().width || 230;
  var radius = (cardWidth / (2 * Math.tan(Math.PI / n))) * 1.35;
  drum.style.setProperty("--radius", radius.toFixed(1) + "px");

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var rotation = 0;
  var velocity = 0;
  var dragging = false;
  var startX = 0;
  var lastX = 0;
  var lastT = 0;
  var moved = 0;
  var momentumId = null;

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
    dragging = true;
    moved = 0;
    startX = lastX = e.clientX;
    lastT = performance.now();
    drum.classList.add("rg-dragging");
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
  }

  drum.addEventListener("pointerdown", onDown);

  // A real drag (past a small threshold) shouldn't also navigate the card
  // the pointer happens to release over — only a genuine, near-stationary
  // click should follow the link.
  cards.forEach(function (card) {
    card.addEventListener("click", function (e) {
      if (moved > 6) e.preventDefault();
    });
  });

  apply();
})();
