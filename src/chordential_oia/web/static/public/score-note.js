/* The review demonstration on /score: mark a moment in a take, say what you heard,
   and watch the note stay on the version it was made against.
 *
 * Separate from score-gl.js on purpose. That file returns early when there is no
 * WebGL2, and the claim this beat makes has to survive that — the demonstration is
 * DOM, the scene is the amplifier. Nothing here touches the renderer.
 *
 * Nothing is sent anywhere. The note lives in sessionStorage and dies with the tab.
 * A public text box that writes to `review_comments` would put anonymous traffic in
 * the same table, and the same code path, as rows carrying contractual weight — and
 * it would need moderation, retention and an identity nobody has. The visitor cannot
 * tell the difference; only an attacker could.
 *
 * The take is silent for now. Every timecode here is a position the visitor chose,
 * so there is no clock to disagree with: when audio arrives, `currentTime` becomes
 * the sole authority for `pos` and nothing else in this file changes.
 */
(function () {
  "use strict";

  var root = document.getElementById("rev");
  if (!root) return;

  var DUR = parseFloat(root.getAttribute("data-seconds")) || 45;
  var KEY = "chordential:score:notes";

  var rail = document.getElementById("revRail");
  var head = document.getElementById("revHead");
  var time = document.getElementById("revTime");
  var mark = document.getElementById("revMark");
  var form = document.getElementById("revForm");
  var text = document.getElementById("revText");
  var list = document.getElementById("revList");
  var none = document.getElementById("revNone");
  var vers = document.getElementById("revVers");

  var audio = document.getElementById("revAudio");
  var playBtn = document.getElementById("revPlay");
  var pos = 0;            // where the visitor is in the take, in seconds
  var held = null;        // the second a pending note was marked at — latched
  var notes = [];
  var version = (function () {
    var on = vers.querySelector(".rev-v.on");
    return on ? on.getAttribute("data-v") : "";
  })();

  function clock(s) {
    s = Math.max(0, Math.min(DUR, s));
    var m = Math.floor(s / 60), r = Math.floor(s % 60);
    return m + ":" + (r < 10 ? "0" : "") + r;
  }

  function load() {
    try {
      var raw = sessionStorage.getItem(KEY);
      notes = raw ? JSON.parse(raw) : [];
      if (!Array.isArray(notes)) notes = [];
    } catch (e) { notes = []; }
  }
  function save() {
    try { sessionStorage.setItem(KEY, JSON.stringify(notes)); } catch (e) {}
  }

  // ── the rail ──────────────────────────────────────────────────────────────
  function setPos(s, fromPointer, fromAudio) {
    pos = Math.max(0, Math.min(DUR, s));
    // currentTime is the authority for anything that binds to the music; the rail
    // writes to it, and only reads back when the element itself moved the playhead
    if (audio && !fromAudio && isFinite(audio.duration) && audio.duration > 0) {
      try { audio.currentTime = pos; } catch (e) {}
    }
    head.style.left = (pos / DUR * 100) + "%";
    time.textContent = clock(pos) + " / " + clock(DUR);
    rail.setAttribute("aria-valuenow", pos.toFixed(1));
    rail.setAttribute("aria-valuetext", clock(pos));
    // while a note is pending the button keeps the second it was marked at: the
    // timecode is latched at the press, not re-read at the submit
    if (held === null) mark.textContent = "Note at " + clock(pos);
    if (fromPointer && held === null) { /* nothing else — moving is not marking */ }
  }

  function posFromEvent(ev) {
    var box = rail.getBoundingClientRect();
    var x = (ev.touches ? ev.touches[0].clientX : ev.clientX) - box.left;
    return (box.width ? x / box.width : 0) * DUR;
  }

  var dragging = false;
  rail.addEventListener("pointerdown", function (ev) {
    if (ev.target.classList.contains("rev-pin")) return;
    dragging = true;
    try { rail.setPointerCapture(ev.pointerId); } catch (e) {}
    setPos(posFromEvent(ev), true);
  });
  rail.addEventListener("pointermove", function (ev) {
    if (dragging) setPos(posFromEvent(ev), true);
  });
  rail.addEventListener("pointerup", function () { dragging = false; });
  rail.addEventListener("pointercancel", function () { dragging = false; });

  rail.addEventListener("keydown", function (ev) {
    var step = ev.shiftKey ? 5 : 1;
    if (ev.key === "ArrowRight") { setPos(pos + step); ev.preventDefault(); }
    else if (ev.key === "ArrowLeft") { setPos(pos - step); ev.preventDefault(); }
    else if (ev.key === "Home") { setPos(0); ev.preventDefault(); }
    else if (ev.key === "End") { setPos(DUR); ev.preventDefault(); }
  });

  // ── marking ───────────────────────────────────────────────────────────────
  mark.addEventListener("click", function () {
    if (held === null) {
      // latch the second NOW. Reading it at submit time would attach the note to
      // wherever the rail happened to be when they finished typing.
      held = pos;
      mark.textContent = clock(held) + " — held";
      form.hidden = false;
      text.value = "";
      text.focus();
    } else {
      commit();
    }
  });

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    commit();
  });

  function commit() {
    if (held === null) return;
    // An empty note still commits. The mark IS the artifact; the words are
    // optional, and a producer who pressed the button and then got pulled into a
    // call has still done the thing.
    notes.push({ t: held, v: version, body: (text.value || "").trim() });
    notes.sort(function (a, b) { return a.t - b.t; });
    held = null;
    form.hidden = true;
    text.value = "";
    save();
    render();
    setPos(pos);
  }

  // ── versions ──────────────────────────────────────────────────────────────
  vers.addEventListener("click", function (ev) {
    var b = ev.target.closest(".rev-v");
    if (!b) return;
    version = b.getAttribute("data-v");
    Array.prototype.forEach.call(vers.querySelectorAll(".rev-v"), function (x) {
      x.classList.toggle("on", x === b);
    });
    if (held !== null) { held = null; form.hidden = true; }
    render();
    setPos(pos);
  });

  // ── rendering ─────────────────────────────────────────────────────────────
  function render() {
    Array.prototype.forEach.call(rail.querySelectorAll(".rev-pin"), function (p) {
      p.remove();
    });
    list.textContent = "";

    var mine = notes.filter(function (n) { return n.v === version; });
    var elsewhere = notes.length - mine.length;

    mine.forEach(function (n) {
      var pin = document.createElement("button");
      pin.type = "button";
      pin.className = "rev-pin";
      pin.style.left = (n.t / DUR * 100) + "%";
      pin.title = clock(n.t) + " · " + n.v;
      pin.setAttribute("aria-label", "Go to " + clock(n.t));
      pin.addEventListener("click", function (ev) {
        ev.stopPropagation();
        setPos(n.t);
      });
      rail.appendChild(pin);

      var li = document.createElement("li");
      var b = document.createElement("b");
      b.textContent = n.body || "(no note — just the moment)";
      var go = document.createElement("button");
      go.type = "button";
      go.textContent = clock(n.t) + " · " + n.v + " · you";
      go.addEventListener("click", function () { setPos(n.t); });
      li.appendChild(b);
      li.appendChild(go);
      list.appendChild(li);
    });

    if (mine.length) {
      none.hidden = true;
    } else {
      none.hidden = false;
      // The proof is an absence. A note that declines to appear on a version it
      // was not made against is the thing no competitor's page can show, so when
      // the visitor switches away from their own note, say why it is gone.
      none.textContent = elsewhere
        ? "Nothing on " + version + ". Your "
          + (elsewhere === 1 ? "note is" : elsewhere + " notes are")
          + " on the version " + (elsewhere === 1 ? "it was" : "they were")
          + " made against — a note does not follow you to a different take."
        : "No notes on this version yet. Scrub the take and drop the first one.";
    }
  }

  if (audio) {
    audio.addEventListener("loadedmetadata", function () {
      if (isFinite(audio.duration) && audio.duration > 0) { DUR = audio.duration; }
      setPos(pos, false, true);
    });
    audio.addEventListener("timeupdate", function () {
      if (!audio.paused) setPos(audio.currentTime, false, true);
    });
    audio.addEventListener("ended", function () {
      playBtn.innerHTML = "&#9654;";
      playBtn.setAttribute("aria-label", "Play the take");
    });
    playBtn.addEventListener("click", function () {
      if (audio.paused) {
        audio.play().then(function () {
          playBtn.innerHTML = "&#10073;&#10073;";
          playBtn.setAttribute("aria-label", "Pause the take");
        }).catch(function () { /* the visitor can press again */ });
      } else {
        audio.pause();
        playBtn.innerHTML = "&#9654;";
        playBtn.setAttribute("aria-label", "Play the take");
      }
    });
  }

  load();
  render();
  setPos(0);
})();
