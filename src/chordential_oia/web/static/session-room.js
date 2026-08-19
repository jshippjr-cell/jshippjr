/* session-room.js — the Session Room live layer (Living OS P5, increment 1).
 *
 * Mounts on any element #session-room carrying data-project / data-role /
 * data-name / data-token(+data-token-kind k|r). Every ~25s it pings presence;
 * every ~6s it polls /project/<id>/session.json?after=<cursor> — the server
 * filters events by ROLE (the trust boundary lives server-side). New events
 * arrive with the halo grammar; presence shows name + role only. Polling
 * transport; the cursor shape is SSE-compatible for the upgrade.
 * Progressive enhancement: without JS the surfaces work exactly as before.
 */
(function () {
  "use strict";
  var root = document.getElementById("session-room");
  if (!root || !window.fetch) return;
  var reduce = window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var pid = root.dataset.project, role = root.dataset.role || "operator";
  var name = root.dataset.name || (role === "operator" ? "Studio" : "Client");
  var token = root.dataset.token || "", tkind = root.dataset.tokenKind || "k";
  var qs = token ? "&" + tkind + "=" + encodeURIComponent(token) : "";
  var after = parseInt(root.dataset.after || "0", 10) || 0;

  /* The FEED is opt-out per mount (`data-feed="0"`). On the delivery console it was
     four rows of note text sitting above the title, restating what the notes queue, the
     review tape and the room all show below it — and pushing the command centre off the
     first screen. *"The comments up at the top of the delivery section is not needed"*
     (operator, 2026-08-19). Presence stays: who else is in the room right now is the one
     thing no other block on that page answers. */
  var wantFeed = (root.dataset.feed || "1") !== "0";
  root.innerHTML =
    '<div class="sr-line">' +
    '<span class="sr-dot" aria-hidden="true"></span>' +
    '<span class="sr-label">Session live</span>' +
    '<span class="sr-faces" aria-hidden="true"></span>' +
    '<span class="sr-who" aria-live="polite"></span></div>' +
    (wantFeed ? '<ul class="sr-feed" aria-live="polite"></ul>' : '');
  var who = root.querySelector(".sr-who"), feed = root.querySelector(".sr-feed"),
      faces = root.querySelector(".sr-faces");

  /* A face per person in the room. Names, not accounts — the client is a buyer with a
     link and the creator is a token, so identity here is the name they are known by.
     The colour is DERIVED from that name, so the same person is the same colour on
     every screen without anyone storing a preference. */
  function initials(n) {
    var parts = String(n || "?").trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return "?";
    return (parts[0][0] + (parts.length > 1 ? parts[parts.length - 1][0] : ""))
      .toUpperCase();
  }
  function hue(n) {
    var h = 0, str = String(n || "");
    for (var i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) % 360;
    return h;
  }
  function renderFaces(people) {
    faces.innerHTML = "";
    people.slice(0, 6).forEach(function (p) {
      var el = document.createElement("span");
      el.className = "sr-face";
      el.textContent = initials(p.name);
      el.title = p.name + " · " + p.role;
      el.style.background = "hsl(" + hue(p.name) + ",58%,42%)";
      faces.appendChild(el);
    });
    if (people.length > 6) {
      var more = document.createElement("span");
      more.className = "sr-face sr-face-more";
      more.textContent = "+" + (people.length - 6);
      faces.appendChild(more);
    }
  }

  var KIND_ICON = { comment: "💬", approval: "✓", version: "♪" };
  function addEvent(e) {
    if (!feed) return;                    // presence-only mount
    var li = document.createElement("li");
    li.className = "sr-ev" + (e.kind === "approval" ? " sr-ev-approval" : "");
    li.innerHTML = '<span class="sr-ico">' + (KIND_ICON[e.kind] || "•") +
      '</span><span class="sr-tx"><b>' + e.name + "</b> · " + e.body +
      '</span><span class="sr-at">' + (e.at || "").slice(11, 16) + "</span>";
    feed.insertBefore(li, feed.firstChild);
    while (feed.children.length > 4) feed.lastChild.remove();
    if (!reduce && window.Live && window.Live.halo) window.Live.halo(li);
  }

  function poll() {
    fetch("/project/" + pid + "/session.json?after=" + after + qs)
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d || d.error) return;
        (d.events || []).forEach(addEvent);
        if (d.last) after = d.last;
        var all = (d.presence || []);
        var others = all.filter(function (p) {
          return !(p.name === name && p.role === role);
        });
        /* Everyone, you included — the room should show you in it, the way a shared
           document does. */
        renderFaces(all.length ? all : [{ name: name, role: role }]);
        who.textContent = others.length
          ? "with you: " + others.map(function (p) {
              return p.name + " · " + p.role; }).join(", ")
          : "you're the only one here";
      }).catch(function () {});
  }
  function ping() {
    var fd = new FormData();
    fd.append("name", name);
    if (token) fd.append(tkind, token);
    fetch("/project/" + pid + "/presence", { method: "POST", body: fd })
      .catch(function () {});
  }
  ping(); poll();
  setInterval(ping, 25000);
  setInterval(poll, 6000);
})();
