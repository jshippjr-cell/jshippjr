(function () {
  "use strict";

  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var coarse = window.matchMedia("(hover: none)").matches;
  // The reduced-motion/touch/narrow-screen CSS fallback already lays these out
  // as a plain static grid — no point computing scroll math nobody will see.
  if (reduce || coarse) return;

  var tiles = Array.prototype.slice.call(document.querySelectorAll(".stl-tile"));
  if (!tiles.length) return;

  // Standard cubic-bezier-to-easing-function solver (Newton-Raphson on the
  // bezier's x(t) to find t for a given x, then evaluate y(t)) — the same
  // approach browsers use internally for `transition-timing-function`, needed
  // here because this animation is scroll-scrubbed (no fixed duration/timeline
  // for CSS's own cubic-bezier() to run against).
  function cubicBezier(x1, y1, x2, y2) {
    function a(u, v) { return 1 - 3 * v + 3 * u; }
    function b(u, v) { return 3 * v - 6 * u; }
    function c(u) { return 3 * u; }
    function bez(t, u, v) { return ((a(u, v) * t + b(u, v)) * t + c(u)) * t; }
    function slope(t, u, v) { return 3 * a(u, v) * t * t + 2 * b(u, v) * t + c(u); }
    return function (x) {
      if (x <= 0) return 0;
      if (x >= 1) return 1;
      var t = x;
      for (var i = 0; i < 8; i++) {
        var dx = bez(t, x1, x2) - x;
        if (Math.abs(dx) < 1e-6) break;
        var d = slope(t, x1, x2);
        if (Math.abs(d) < 1e-6) break;
        t -= dx / d;
      }
      return bez(t, y1, y2);
    };
  }
  var easeIntoFocus = cubicBezier(0.22, 1, 0.36, 1);
  var easeOutOfFocus = cubicBezier(0, 0, 0.58, 1);

  function lerp(a, b, t) { return a + (b - a) * t; }

  // Every animated value follows the same three-keyframe shape: an entrance
  // pose (progress 0), sharp focus (0.5), an exit pose (1) — eased into focus
  // on the way in, eased out of focus on the way out.
  function threePoint(progress, v0, v05, v1) {
    if (progress <= 0.5) return lerp(v0, v05, easeIntoFocus(progress / 0.5));
    return lerp(v05, v1, easeOutOfFocus((progress - 0.5) / 0.5));
  }

  var MAX_TILT = 70;
  var MAX_BLUR = 8;
  var TZ = 300;

  var active = new Set();
  var io = new IntersectionObserver(
    function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          active.add(entry.target);
          entry.target.classList.add("stl-active");
        } else {
          active.delete(entry.target);
          entry.target.classList.remove("stl-active");
        }
      });
    },
    { rootMargin: "50% 0px 50% 0px" }
  );
  tiles.forEach(function (tile, i) {
    tile.dataset.stlSign = i % 2 === 0 ? "-1" : "1";
    io.observe(tile);
  });

  var ticking = false;
  function update() {
    ticking = false;
    var vh = window.innerHeight;
    active.forEach(function (tile) {
      var frame = tile.querySelector(".stl-frame");
      if (!frame) return;
      var rect = tile.getBoundingClientRect();
      // Matches the "start end" -> "end start" scroll-offset convention: 0
      // when the tile's top edge reaches the viewport's bottom edge, 1 when
      // the tile's bottom edge reaches the viewport's top edge.
      var raw = (vh - rect.top) / (vh + rect.height);
      var p = Math.max(0, Math.min(1, raw));
      var sign = parseFloat(tile.dataset.stlSign);

      var tx = threePoint(p, sign * 40, 0, sign * 40);
      var ty = threePoint(p, 100, 0, -100);
      var tz = threePoint(p, TZ, 0, TZ);
      var rot = threePoint(p, -sign * 5, 0, sign * 5);
      var rx = threePoint(p, MAX_TILT, 0, -MAX_TILT);
      var sk = threePoint(p, sign * 20, 0, -sign * 20);
      var blur = threePoint(p, MAX_BLUR, 0, MAX_BLUR);
      var bright = threePoint(p, 0, 1, 0);
      var contrast = threePoint(p, 4, 1, 4);
      var innerY = threePoint(p, 1.8, 1, 1.8);

      frame.style.setProperty("--stl-tx", tx + "%");
      frame.style.setProperty("--stl-ty", ty + "%");
      frame.style.setProperty("--stl-tz", tz + "px");
      frame.style.setProperty("--stl-rot", rot + "deg");
      frame.style.setProperty("--stl-rx", rx + "deg");
      frame.style.setProperty("--stl-sk", sk + "deg");
      frame.style.setProperty("--stl-blur", blur + "px");
      frame.style.setProperty("--stl-bright", bright);
      frame.style.setProperty("--stl-contrast", contrast);

      var img = tile.querySelector(".stl-img");
      if (img) img.style.setProperty("--stl-inner", innerY);
    });
  }
  function onScroll() {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(update);
  }

  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", onScroll);
  onScroll();
})();
