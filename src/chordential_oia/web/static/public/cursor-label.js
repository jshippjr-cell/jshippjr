/* Cursor-following label — the keystone interaction.
 *
 * A small pill that trails the mouse with a subtle lerp. Its text is driven by the
 * `data-cursor` attribute of whatever you hover (default "play"). Desktop only:
 * disabled on touch (no pointer) and when the user prefers reduced motion — there a
 * real button is shown instead (see showreel.html). Pure vanilla, no dependencies.
 */
(function () {
  var stage = document.querySelector('[data-cursor-stage]');
  var pill = document.querySelector('.sr-cursor');
  if (!stage || !pill) return;

  // Respect touch + reduced-motion: no custom cursor, the page shows tap controls.
  var fine = window.matchMedia('(hover: hover) and (pointer: fine)').matches;
  var calm = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (!fine) { document.body.classList.add('is-touch'); return; }

  var tx = window.innerWidth / 2, ty = window.innerHeight / 2;  // target
  var x = tx, y = ty;                                            // eased position
  var label = 'play';
  var visible = false;

  stage.addEventListener('pointermove', function (e) {
    tx = e.clientX; ty = e.clientY;
    if (!visible) { visible = true; pill.classList.add('on'); }
    // Read the contextual label from the hovered element (or its closest owner).
    var owner = e.target.closest('[data-cursor]');
    label = (owner && owner.getAttribute('data-cursor')) || 'play';
  });
  stage.addEventListener('pointerleave', function () {
    visible = false; pill.classList.remove('on');
  });

  function frame() {
    // Lerp toward the target for the trailing feel (snap if reduced-motion).
    var k = calm ? 1 : 0.2;
    x += (tx - x) * k; y += (ty - y) * k;
    pill.style.transform = 'translate(' + x + 'px,' + y + 'px) translate(-50%,-50%)';
    if (pill.textContent !== label) pill.textContent = label;
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
})();
