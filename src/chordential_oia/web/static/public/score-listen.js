/* Pressing a live note opens the player. Nothing plays before that press.
 *
 * Separate from the renderer for the same reason as the review demo: score-gl.js
 * returns early with no WebGL2, and while the lit NOTES need the scene, the tracks
 * must still be reachable without it — so this file falls back to a plain list.
 *
 * No AudioContext, no createMediaElementSource. ADR-0043's fourth amendment
 * documents what tapping a media element cost in production: a client in silence
 * with `audio.paused === false`, no MediaError, and every instrument reporting
 * green. Nothing on the page where audio IS the pitch is worth that risk.
 */
(function () {
  "use strict";
  var node = document.getElementById("scoretracks");
  if (!node) return;
  var tracks = [];
  try { tracks = JSON.parse(node.textContent) || []; } catch (e) { tracks = []; }
  window.__SCORE_TRACKS = tracks;
  if (!tracks.length) return;

  var box = document.getElementById("player");
  var audio = document.getElementById("plAudio");
  var elTitle = document.getElementById("plTitle");
  var elBrief = document.getElementById("plBrief");
  var elDisc = document.getElementById("plDisc");
  var elCost = document.getElementById("plCost");
  var closeBtn = document.getElementById("playerX");

  function clock(s) {
    var m = Math.floor(s / 60), r = Math.floor(s % 60);
    return m + ":" + (r < 10 ? "0" : "") + r;
  }

  function open(i) {
    var t = tracks[i];
    if (!t) return;
    elDisc.textContent = t.discipline;
    elTitle.textContent = t.title;
    elBrief.textContent = t.brief;
    // the cost is on the page BEFORE the press: a producer on hotel wifi has been
    // burned by a landing page that spent four megabytes without asking
    elCost.textContent = clock(t.seconds) + " · " + t.mb + " MB · excerpt";
    if (audio.getAttribute("src") !== t.url) {
      audio.setAttribute("src", t.url);
      audio.load();
    }
    box.hidden = false;
    audio.play().catch(function () { /* the visitor can press the control */ });
    closeBtn.focus();
  }

  function close() {
    audio.pause();
    box.hidden = true;
  }

  closeBtn.addEventListener("click", close);
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape" && !box.hidden) close();
  });

  // the renderer builds the hotspots once it has the scene; catch clicks by
  // delegation so this file does not care when that happens
  document.addEventListener("click", function (ev) {
    var el = ev.target.closest ? ev.target.closest(".livenote") : null;
    if (!el) return;
    open(parseInt(el.dataset.track, 10));
  });

  // No WebGL2, no lit notes, no way in. Fall back to a plain list rather than
  // leaving the music unreachable — the words are not a substitute for the work.
  window.addEventListener("load", function () {
    setTimeout(function () {
      if (document.querySelector(".livenote")) return;
      var hint = document.getElementById("ltHint");
      if (!hint) return;
      hint.textContent = "Hear what we sound like:";
      var ul = document.createElement("ul");
      ul.className = "lt-fallback";
      tracks.forEach(function (t, i) {
        var li = document.createElement("li");
        var b = document.createElement("button");
        b.type = "button";
        b.textContent = t.title + " · " + t.discipline;
        b.addEventListener("click", function () { open(i); });
        li.appendChild(b);
        ul.appendChild(li);
      });
      hint.parentNode.insertBefore(ul, hint.nextSibling);
    }, 1200);
  });
})();
