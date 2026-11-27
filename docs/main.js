// Point the download button at the latest release's .pkg, and add copy
// buttons to code blocks. The page works without either.

(function () {
  "use strict";

  var REPO = "svdimchenko/Xerox-WorkCentre-3025-SpliX";

  function formatSize(bytes) {
    if (bytes < 1024 * 1024) return Math.max(1, Math.round(bytes / 1024)) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function showRelease(release) {
    var asset = (release.assets || []).filter(function (a) {
      return /\.pkg$/.test(a.name);
    })[0];
    if (!asset) return;

    var version = String(release.tag_name || "").replace(/^v/, "");
    document.getElementById("download").href = asset.browser_download_url;
    document.getElementById("download-label").textContent =
      "Download v" + version + " (.pkg, " + formatSize(asset.size) + ")";

    var date = new Date(release.published_at);
    var meta = document.getElementById("release-meta");
    meta.textContent = "Released " + date.toLocaleDateString(undefined, {
      year: "numeric", month: "long", day: "numeric"
    }) + ". Free, GPL-2.0. Printing only; scanning isn't included.";

    Array.prototype.forEach.call(document.querySelectorAll(".pkg-name"), function (el) {
      el.textContent = asset.name;
    });
    Array.prototype.forEach.call(document.querySelectorAll(".driver-name"), function (el) {
      el.textContent = "Xerox WorkCentre 3025 SpliX, " + version;
    });
  }

  if (window.fetch) {
    fetch("https://api.github.com/repos/" + REPO + "/releases/latest", {
      headers: { Accept: "application/vnd.github+json" }
    })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (release) { if (release) showRelease(release); })
      .catch(function () { /* keep the link to the releases page */ });
  }

  if (navigator.clipboard) {
    Array.prototype.forEach.call(document.querySelectorAll("pre"), function (pre) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "copy";
      button.textContent = "Copy";
      button.addEventListener("click", function () {
        var text = pre.querySelector("code").textContent;
        navigator.clipboard.writeText(text).then(function () {
          button.textContent = "Copied";
          setTimeout(function () { button.textContent = "Copy"; }, 1500);
        });
      });
      pre.appendChild(button);
    });
  }
})();
