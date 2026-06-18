/* Match Board — assign talent to an opportunity by drag-and-drop (desktop) or
   tap-to-pick then tap-an-opportunity (touch). Posts to the server and reloads. */
(function () {
  "use strict";
  var picked = null;

  function clearPicked() {
    document.querySelectorAll(".mb-bubble.picked").forEach(function (x) {
      x.classList.remove("picked");
    });
    picked = null;
    document.body.classList.remove("mb-picking");
  }

  function assign(talentId, oppId) {
    if (!talentId || !oppId) return;
    var body = new URLSearchParams();
    body.set("opp_id", oppId);
    body.set("talent_id", talentId);
    fetch("/matchboard/assign", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body.toString(),
    }).then(function () {
      window.location.reload();
    });
  }

  document.querySelectorAll(".mb-bubble").forEach(function (b) {
    b.addEventListener("dragstart", function (e) {
      e.dataTransfer.setData("text/plain", b.dataset.talentId);
      e.dataTransfer.effectAllowed = "copy";
      b.classList.add("dragging");
    });
    b.addEventListener("dragend", function () {
      b.classList.remove("dragging");
    });
    // tap-to-pick (works on touch + mouse)
    b.addEventListener("click", function () {
      if (picked === b) { clearPicked(); return; }
      clearPicked();
      picked = b;
      b.classList.add("picked");
      document.body.classList.add("mb-picking");
    });
  });

  document.querySelectorAll(".mb-opp").forEach(function (o) {
    o.addEventListener("dragover", function (e) {
      e.preventDefault();
      o.classList.add("over");
    });
    o.addEventListener("dragleave", function () {
      o.classList.remove("over");
    });
    o.addEventListener("drop", function (e) {
      e.preventDefault();
      o.classList.remove("over");
      assign(e.dataTransfer.getData("text/plain"), o.dataset.oppId);
    });
    // tap an opportunity while a creator is picked → assign (touch flow)
    o.addEventListener("click", function (e) {
      if (picked && !e.target.closest("a") && !e.target.closest("button")) {
        assign(picked.dataset.talentId, o.dataset.oppId);
      }
    });
  });
})();
