/* Portfolio lightbox.
 *
 * Progressive enhancement: without this file every tile is a plain link to the
 * full-size image, and timelapse tiles show their poster frame. With it, tiles
 * open a <dialog> lightbox with keyboard navigation.
 */
(function () {
  "use strict";

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

  // --- tile preview autoplay (only when motion is allowed) ------------------
  function startPreviews() {
    if (reduceMotion.matches) return;
    document.querySelectorAll("video.tile-media[data-preview]").forEach(function (v) {
      if (v.dataset.started) return;
      v.dataset.started = "1";
      v.src = v.dataset.preview;
      v.load();
      var p = v.play();
      if (p && p.catch) p.catch(function () { /* autoplay blocked — poster stays */ });
    });
  }
  startPreviews();
  if (reduceMotion.addEventListener) {
    reduceMotion.addEventListener("change", startPreviews);
  }

  // --- lightbox ------------------------------------------------------------
  var dialog = document.getElementById("lightbox");
  var dataEl = document.getElementById("artworks-data");
  if (!dialog || !dataEl || typeof dialog.showModal !== "function") return;

  var artworks = [];
  try {
    artworks = JSON.parse(dataEl.textContent);
  } catch (e) {
    return; // leave plain-link behaviour in place
  }

  var body = document.getElementById("lightbox-body");
  var caption = document.getElementById("lightbox-caption");
  var current = 0;
  var opener = null;

  function render(i) {
    var art = artworks[i];
    if (!art) return;
    current = i;

    // Stop any playing video before swapping it out.
    var old = body.querySelector("video");
    if (old) old.pause();
    body.innerHTML = "";

    if (art.video) {
      var v = document.createElement("video");
      v.src = art.video.full;
      v.poster = art.video.poster;
      v.controls = true;
      v.playsInline = true;
      v.preload = "metadata";
      body.appendChild(v);
    } else {
      var img = document.createElement("img");
      img.src = art.image.full;
      img.alt = art.title;
      body.appendChild(img);
    }
    // Working titles hidden here too (see templates/index.html.j2) so the
    // lightbox doesn't reveal what the grid just hid. Restore by putting
    // `art.title + " "` back in front once the pieces have real names.
    caption.textContent = "(" + (i + 1) + "/" + artworks.length + ")";
  }

  function open(i, fromEl) {
    opener = fromEl || document.activeElement;
    render(i);
    dialog.showModal();
    var btn = dialog.querySelector("[data-close]");
    if (btn) btn.focus();
  }

  function close() {
    var v = body.querySelector("video");
    if (v) v.pause();
    if (dialog.open) dialog.close();
  }

  function step(delta) {
    var n = artworks.length;
    render((current + delta + n) % n);
  }

  document.querySelectorAll(".tile-link").forEach(function (link) {
    link.addEventListener("click", function (e) {
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
      e.preventDefault();
      open(parseInt(link.dataset.index, 10) || 0, link);
    });
  });

  dialog.addEventListener("click", function (e) {
    if (e.target === dialog || e.target.hasAttribute("data-close")) close();
    if (e.target.hasAttribute("data-prev")) step(-1);
    if (e.target.hasAttribute("data-next")) step(1);
  });

  dialog.addEventListener("keydown", function (e) {
    if (e.key === "ArrowLeft") { e.preventDefault(); step(-1); }
    if (e.key === "ArrowRight") { e.preventDefault(); step(1); }
  });

  dialog.addEventListener("close", function () {
    if (opener && typeof opener.focus === "function") opener.focus();
    body.innerHTML = "";
  });
})();
