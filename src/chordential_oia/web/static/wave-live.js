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
   * A still waveform is a decoration we can live without. Silence is not.
   *
   * THE SECOND WAY IT SILENCED THE PRODUCT, which is worse because it needs no unlucky
   * timing at all. A `MediaElementAudioSourceNode` fed by CROSS-ORIGIN media that is not
   * CORS-approved is required by spec to output SILENCE — the analyser must not become a
   * way to read bytes across origins. Not an error: silence, while the element reports it
   * is playing. Measured, one page, two elements, identical code: same-origin peak 222 /
   * energy 8564; cross-origin peak 0 / energy 0.
   *
   * `/uploads/{name}` redirects to a presigned bucket URL whenever a durable object store
   * is configured, so on such an instance EVERY client cut is cross-origin and every one
   * of them plays silent through this graph. That is exactly what happened: the day the
   * bucket was switched on, every version in the review portal went silent — including
   * mp3s uploaded long before — and nothing anywhere reported it, because nothing was
   * broken. A redirect cannot be detected from here (the element keeps the requested URL
   * in `currentSrc`), so the server says so instead. Default is DON'T TAP.
   *
   * GETTING THE WAVE BACK ON A BUCKET, WITHOUT BETTING THE AUDIO ON IT. Cross-origin media
   * CAN be tapped — if the bucket returns CORS headers and the element carries
   * `crossorigin="anonymous"`. The trap is that setting that attribute against a bucket
   * with no CORS rule does not degrade to a silent wave, it makes the media fail to load
   * outright: the client loses playback entirely to buy a decoration. So the attribute is
   * never set on faith. Each player PROVES the bytes are CORS-readable first, with a
   * one-byte `Range` fetch shaped exactly like the request the media element will make,
   * fired at page load while `preload="none"` means nothing has loaded yet. Only on a
   * proven-readable response does the element get `crossorigin` and the tap. And if the
   * media still fails afterwards, the element drops the attribute, reloads, resumes, and
   * gives up on the wave for good — playback is the thing that must survive. */

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

    /* Same-origin media is readable by definition. Cross-origin media is not tapped until
       a probe proves otherwise, and `loading` records whether the element has already
       started fetching — past that point the `crossorigin` attribute cannot be added
       without a reload, so we let this session play un-analysed rather than interrupt it. */
    var canTap = !mayBeCrossOrigin(audio), loading = false;
    audio.addEventListener("loadstart", function () { loading = true; });

    if (!canTap) proveReadable(audio, function () {
      if (loading) return;                     // too late to switch the element safely
      audio.crossOrigin = "anonymous";         // preload="none": nothing fetched yet
      // Handshake with the player's own error handler: while this is set, a load failure
      // belongs to US and we are going to undo it, so the player must not tell the client
      // the file is broken — it is about to play.
      audio.dataset.waveCors = "1";
      canTap = true;
      recoverIfMediaFails(player, audio, cv, function () { canTap = false; failed = true; });
    });

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

    /* Only ever called with a RUNNING context, and only on audio this player has proven
       it is allowed to read — see the note at the top. */
    function tap() {
      if (failed || analyser || !ctx || ctx.state !== "running") return;
      if (!canTap) { failed = true; cv.remove(); return; }
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

  /* Is this element's audio liable to come from another origin?
   *
   * `/uploads/{name}` 307s to a presigned bucket URL whenever the instance has a durable
   * object store, and the element keeps the REQUESTED url in `currentSrc`, so a redirect
   * is invisible from here. The server therefore stamps the script tag
   * (`wave-live.js?...&offsite=1`) and every /uploads element is off limits on such an
   * instance. Anything already on another origin is refused outright.
   *
   * Fails CLOSED. If the flag cannot be read for any reason, we assume off-site and skip
   * the tap: the cost of being wrong that way is a still waveform, and the cost of being
   * wrong the other way is a client hearing nothing with no error to show for it. */
  var OFFSITE = true;
  try {
    var me = document.currentScript ||
             document.querySelector('script[src*="wave-live.js"]');
    // ONLY an explicit offsite=0 opens the tap. A template that forgets the flag, a
    // script tag we cannot find, or a file:// bundle all leave it closed — the failure
    // we are guarding against is inaudible, so the default has to be the safe one.
    OFFSITE = location.protocol === "file:" || !me ||
              !/[?&]offsite=0(&|$)/.test(me.getAttribute("src") || "");
  } catch (e) { OFFSITE = true; }

  function mayBeCrossOrigin(audio) {
    var src = audio.getAttribute("src") || audio.currentSrc || "";
    try {
      var u = new URL(src, location.href);
      if (u.origin !== location.origin) return true;      // already elsewhere
      return OFFSITE && u.pathname.indexOf("/uploads/") === 0;
    } catch (e) { return true; }
  }

  /* Can this media be read across origins? Asked with the SAME request the media element
     will make — a GET with a one-byte Range — because a CORS rule that allows a bare GET
     but not the `range` header would pass a lazier probe and then fail the real load.
     `no-store` so the answer is never a cached response from before the rule existed. */
  function proveReadable(audio, ok) {
    var src = audio.getAttribute("src") || "";
    if (!src || !window.fetch) return;
    try {
      fetch(src, { method: "GET", mode: "cors", cache: "no-store",
                   headers: { Range: "bytes=0-0" } })
        .then(function (r) { if (r.ok || r.status === 206) ok(); })
        .catch(function () { /* no CORS rule: the wave stays still, the audio plays */ });
    } catch (e) { /* same */ }
  }

  /* Last line of defence. If the media fails AFTER we added `crossorigin` — a rule that
     covers HEAD but not GET, an origin list that misses this host, a rule removed later —
     take the attribute back off, reload, and carry on WITHOUT the wave. The client keeps
     the audio; we lose a decoration. Also clears the player's failure banner, which by
     then is telling the listener something that is about to stop being true. */
  function recoverIfMediaFails(player, audio, cv, giveUp) {
    audio.addEventListener("error", function onErr() {
      if (!audio.crossOrigin) return;
      audio.removeEventListener("error", onErr);
      var at = audio.currentTime || 0;
      giveUp();
      try { cv.remove(); } catch (e) {}
      audio.removeAttribute("crossorigin");
      delete audio.dataset.waveCors;           // a LATER failure is genuine; let it show
      audio.load();
      if (at) { try { audio.currentTime = at; } catch (e) {} }
      player.classList.remove("failed");
      var note = player.parentNode && player.parentNode.querySelector(".cap-audio-err");
      if (note) note.remove();
      var btn = player.querySelector(".cap-audio-btn");
      if (btn) { btn.textContent = "▶"; btn.setAttribute("aria-label", "Play"); }
      var t = player.querySelector(".cap-audio-time");
      if (t) t.textContent = "0:00";
      var pr = audio.play(); if (pr && pr.catch) pr.catch(function () {});
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
