// Inserted by tools/build_pages.py as the first script of every page in the Cloudflare Pages build.
// The pages are static there, but they call the planner's server with root paths ("/api/…", "/murray/…" map
// tiles, "/terrain/…" elevation). This sends those requests to the public server instead, so the front-end
// code stays the same as when the server hosts it. The server allows cross-origin requests (CORS "*").
(function () {
  "use strict";
  var API = "__MARSWALK_API__".replace(/\/+$/, "");
  var SERVER_PATH = /^\/(api|murray|terrain|cubes|tiles|ctxtiles)(\/|$)/;
  window.MARSWALK_API = API;

  // "/api/x", "api/x" from the root page, or "https://<this site>/api/x" -> "<API>/api/x"; anything else unchanged
  function toServer(value) {
    if (value == null) return null;
    try {
      var url = new URL(String(value), location.href);
      if (url.origin !== location.origin || !SERVER_PATH.test(url.pathname)) return null;
      return API + url.pathname + url.search + url.hash;
    } catch (e) { return null; }
  }
  window.marswalkServerUrl = function (value) { return toServer(value) || value; };

  var fetch0 = window.fetch;
  window.fetch = function (input, init) {
    if (typeof input === "string" || input instanceof URL) {
      input = toServer(input) || input;
    } else if (input && typeof input.url === "string") {
      var moved = toServer(input.url);
      if (moved) input = new Request(moved, input);
    }
    return fetch0.call(this, input, init);
  };

  var open0 = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url) {
    var moved = toServer(url);
    if (moved) arguments[1] = moved;
    return open0.apply(this, arguments);
  };

  if (window.EventSource) {
    var EventSource0 = window.EventSource;
    window.EventSource = function (url, options) { return new EventSource0(toServer(url) || url, options); };
    window.EventSource.prototype = EventSource0.prototype;
  }

  // images (map tiles drawn by Cesium, photos) set by property or attribute. A moved image must be requested
  // with CORS: Cesium thinks "/murray/…" is same-origin and doesn't ask for it, and Safari then refuses to
  // upload the cross-origin pixels to WebGL ("SecurityError: The operation is insecure", rendering stops).
  // The server answers CORS requests (allow_origins="*").
  function corsFor(img) { if (!img.crossOrigin) img.crossOrigin = "anonymous"; }
  var src = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, "src");
  Object.defineProperty(HTMLImageElement.prototype, "src", {
    configurable: true, enumerable: src.enumerable, get: src.get,
    set: function (value) {
      var moved = toServer(value);
      if (moved) corsFor(this);
      src.set.call(this, moved || value);
    },
  });
  var setAttribute0 = Element.prototype.setAttribute;
  Element.prototype.setAttribute = function (name, value) {
    if (this instanceof HTMLImageElement && String(name).toLowerCase() === "src") {
      var moved = toServer(value);
      if (moved) { corsFor(this); value = moved; }
    }
    return setAttribute0.call(this, name, value);
  };

  // links to server pages (e.g. "/api/weather/sources"), including ones added later
  document.addEventListener("click", function (event) {
    var link = event.target && event.target.closest && event.target.closest("a[href]");
    var moved = link && toServer(link.getAttribute("href"));
    if (moved) link.href = moved;
  }, true);
})();
