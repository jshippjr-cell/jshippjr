/* wave-live.js — the alive waveform (Living OS P4).
 *
 * Upgrades every .cap-audio player: a slim canvas whose bars move with the
 * REAL spectral energy of the audio element (AnalyserNode) while it plays —
 * never an animation loop (council ruling). At rest the wave is still and
 * calm (client-facing surfaces stay quiet); if AudioContext is unavailable
 * or the source can't be tapped, the canvas is removed and the original
 * progress bar keeps working untouched. Playback is never intercepted or
 * delayed — the analyser taps the signal on the existing 'play' event.
 */
(function () {
  "use strict";
  if (window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

  var AC = window.AudioContext || window.webkitAudioContext;
  if (!AC) return;                            // graceful: old player untouched
  var ctx = null;                             // one shared context, lazily
  var dpr = Math.min(window.devicePixelRatio || 1, 2);
  var BARS = 40;

  /* THE RULE THIS FILE BROKE, AND WHY THE GUARD BELOW IS NOT OPTIONAL.
   *
   * `createMediaElementSource(audio)` does not observe the element — it CAPTURES it.
   * The moment it is called, the element stops feeding the speakers and its only route
   * to them is through this graph. So if the AudioContext is suspended, the client hears
   * nothing, `audio.paused` is still false, no MediaError fires, and no error handler
   * anywhere can see it: the file is fine, the network is fine, the player says it is
   * playing. Measured in a browser — element playing, `ctx.state` suspended, the graph's
   * clock frozen at 0, not one visible signal. A client sat in front of exactly that and
   * reported "silence", and it cost several rounds to find because every other layer was
   * healthy and said so.
   *
   * The context was being built inside the `play` event handler, which is not reliably
   * inside the user-gesture window — Chrome then starts it suspended, `resume()` is a
   * promise nobody awaited, and the audio is already captured by then. So: build and
   * resume it on the real click, and TAP NOTHING until the context is actually running.
   * A still waveform is a decoration we can live without. Silence is not. */

  function upgrade(player) {
    var audio = player.querySelector("audio");
    var body = player.querySelector(".cap-audio-body");
    if (!audio || !body || player.dataset.waveLive) return;
    player.dataset.waveLive = "1";

    var cv = document.createElement("canvas");
    cv.className = "cap-wave";
    cv.setAttribute("aria-hidden", "true");
    body.insertBefore(cv, body.firstChild);
    var g2 = cv.getContext("2d"), W = 0, H = 18;

    function size() {
      var r = cv.getBoundingClientRect();
      if (r.width < 4) return;
      W = r.width;
      cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
      g2.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    window.addEventListener("resize", size); size();

    // the still wave — a deterministic quiet silhouette until sound flows
    var still = [];
    for (var i = 0; i < BARS; i++) {
      var t = i / BARS;
      still.push(Math.max(.15, Math.min(1, t * 7) * Math.min(1, (1 - t) * 6) *
        (0.45 + 0.55 * Math.abs(Math.sin(i * 0.8) * Math.sin(i * 0.31)))));
    }
    var smooth = still.slice(), analyser = null, freq = null, raf = null, failed = false;

    function band(i) {
      if (!analyser) return 0;
      var n = freq.length;
      var lo = Math.floor(Math.pow(i / BARS, 1.6) * n * 0.75);
      var hi = Math.max(lo + 1, Math.floor(Math.pow((i + 1) / BARS, 1.6) * n * 0.75));
      var s = 0; for (var b = lo; b < hi; b++) s += freq[b];
      return (s / (hi - lo)) / 255;
    }
    function draw() {
      if (!W) size();
      var playing = !audio.paused && !audio.ended;
      if (playing && analyser) analyser.getByteFrequencyData(freq);
      g2.clearRect(0, 0, W, H);
      var gap = 1.5, bw = (W - (BARS - 1) * gap) / BARS, mid = H / 2;
      var edge = (audio.duration ? audio.currentTime / audio.duration : 0) * BARS;
      for (var i = 0; i < BARS; i++) {
        var target = playing ? Math.min(1.2, still[i] * (0.5 + 1.1 * band(i))) : still[i];
        smooth[i] += (target - smooth[i]) * (playing ? 0.3 : 0.12);
        var h = Math.max(2, smooth[i] * (H - 2)), x = i * (bw + gap);
        g2.fillStyle = i < edge ? "#E4671F" : "#D8CDB6";
        g2.beginPath();
        g2.roundRect ? g2.roundRect(x, mid - h / 2, bw, h, bw / 2)
                     : g2.rect(x, mid - h / 2, bw, h);
        g2.fill();
      }
      if (playing) raf = requestAnimationFrame(draw);
      else raf = null;
    }
    draw();                                    // paint the still wave once

    /* Only ever called with a RUNNING context — see the note at the top. */
    function tap() {
      if (failed || analyser || !ctx || ctx.state !== "running") return;
      try {
        var src = ctx.createMediaElementSource(audio);
        analyser = ctx.createAnalyser();
        analyser.fftSize = 128; analyser.smoothingTimeConstant = 0.72;
        freq = new Uint8Array(analyser.frequencyBinCount);
        src.connect(analyser); analyser.connect(ctx.destination);
      } catch (e) {                            // tap failed: remove the canvas,
        failed = true; analyser = null; cv.remove();   // the original bar still works
      }
    }

    /* The click is the user gesture; the `play` event is not reliably inside it. Capture
       phase so this runs before the handler that calls play(). */
    player.addEventListener("click", gestureContext, true);

    audio.addEventListener("play", function () {
      tap();                                   // no-op unless the context is running
      if (!raf) raf = requestAnimationFrame(draw);
    });
    audio.addEventListener("pause", function () { setTimeout(draw, 50); });
    audio.addEventListener("timeupdate", function () {
      // A context resumed a moment after play started can still be tapped — but only
      // once it is genuinely running, never on the promise of it.
      if (!analyser) tap();
      if (!raf) draw();
    });
  }

  /* Build and resume the shared context from inside a real user gesture. Nothing here
     touches the audio element: a context that never reaches "running" must leave the
     player exactly as it found it. */
  function gestureContext() {
    try { ctx = ctx || new AC(); } catch (e) { return; }
    if (ctx.state === "suspended" && ctx.resume) {
      var pr = ctx.resume();
      if (pr && pr.catch) pr.catch(function () {});
    }
  }

  function init() {
    document.querySelectorAll(".cap-audio").forEach(upgrade);
  }
  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", init);
  else init();
})();
