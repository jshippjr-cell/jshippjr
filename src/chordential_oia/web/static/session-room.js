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

  root.innerHTML =
    '<div class="sr-line">' +
    '<span class="sr-dot" aria-hidden="true"></span>' +
    '<span class="sr-label">Session live</span>' +
    '<span class="sr-who" aria-live="polite"></span></div>' +
    '<ul class="sr-feed" aria-live="polite"></ul>';
  var who = root.querySelector(".sr-who"), feed = root.querySelector(".sr-feed");

  var KIND_ICON = { comment: "💬", approval: "✓", version: "♪" };
  function addEvent(e) {
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
        var others = (d.presence || []).filter(function (p) {
          return !(p.name === name && p.role === role);
        });
        who.textContent = others.length
          ? "in the room: " + others.map(function (p) {
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
