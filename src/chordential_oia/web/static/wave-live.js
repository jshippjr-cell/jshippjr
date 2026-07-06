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

    audio.addEventListener("play", function () {
      if (!failed && !analyser) {
        try {
          ctx = ctx || new AC();
          if (ctx.state === "suspended") ctx.resume();
          var src = ctx.createMediaElementSource(audio);
          analyser = ctx.createAnalyser();
          analyser.fftSize = 128; analyser.smoothingTimeConstant = 0.72;
          freq = new Uint8Array(analyser.frequencyBinCount);
          src.connect(analyser); analyser.connect(ctx.destination);
        } catch (e) {                          // tap failed: remove the canvas,
          failed = true; cv.remove(); return;  // the original bar still works
        }
      }
      if (!raf) raf = requestAnimationFrame(draw);
    });
    audio.addEventListener("pause", function () { setTimeout(draw, 50); });
    audio.addEventListener("timeupdate", function () { if (!raf) draw(); });
  }

  function init() {
    document.querySelectorAll(".cap-audio").forEach(upgrade);
  }
  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", init);
  else init();
})();
