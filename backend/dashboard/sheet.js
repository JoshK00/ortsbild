// The bottom sheets of the phone layout: where they stop. Plain functions without the page, so they can be tested with node
// (see tests/dashboard_sheet.test.js). The page code (app.js) only moves the pixels.
(function (root) {
  "use strict";

  var PEEK_HEIGHT = 188; // handle, title, count and the first report
  var FLING_MS = 180; // how far ahead a moving finger is followed: height + speed * this
  var TAP_PX = 6; // a touch that moves less than this is a tap, not a drag
  var TAP_MS = 400;
  var MIN_STEP = 60; // two stops are at least this far apart, also on a small screen (a phone on its side)

  // The three stops of the list in pixels, for a window of `viewport` pixels height. `topInset` is what stays free above the
  // sheet when it is fully open (the safe area, the filter chips). `bottomInset` is the safe area under the sheet: it is part
  // of the sheet, so the content of the peek stays as large as it was.
  function snapPoints(viewport, topInset, bottomInset) {
    var peek = Math.min(PEEK_HEIGHT + (bottomInset || 0), Math.round(viewport * 0.34));
    var half = Math.max(peek + MIN_STEP, Math.round(viewport * 0.5));
    var full = Math.max(half + MIN_STEP, Math.round(viewport - (topInset || 0)));
    return { peek: peek, half: half, full: full };
  }

  // The stops as a sorted list: [{name, height}], for `nearest`. The detail has one more stop, "closed" at height 0.
  function stops(points, names) {
    return names.map(function (name) { return { name: name, height: name === "closed" ? 0 : points[name] }; })
      .sort(function (a, b) { return a.height - b.height; });
  }

  function clamp(value, low, high) { return Math.min(high, Math.max(low, value)); }

  // Where a sheet comes to rest after the finger is lifted. `velocity` is in pixels per millisecond, positive = the sheet grows
  // (the finger moved up). The sheet follows the finger a little further than where it is, so a flick goes to the next stop.
  function nearest(height, velocity, list) {
    var projected = height + (velocity || 0) * FLING_MS;
    var best = list[0];
    list.forEach(function (stop) {
      if (Math.abs(stop.height - projected) < Math.abs(best.height - projected)) best = stop;
    });
    return best.name;
  }

  // The speed of the last moments of a drag from the samples [{t, y}] (y in pixels, downwards). Positive = the sheet grows.
  function velocityOf(samples) {
    if (!samples || samples.length < 2) return 0;
    var last = samples[samples.length - 1];
    var first = samples[0];
    for (var i = samples.length - 1; i >= 0; i--) {
      if (last.t - samples[i].t > 100) break;
      first = samples[i];
    }
    var dt = last.t - first.t;
    return dt > 0 ? (first.y - last.y) / dt : 0;
  }

  // A tap on the handle moves to the next stop, from the biggest back to the smallest.
  function next(current, names) {
    var index = names.indexOf(current);
    return names[(index + 1) % names.length];
  }

  var api = {
    PEEK_HEIGHT: PEEK_HEIGHT, TAP_PX: TAP_PX, TAP_MS: TAP_MS,
    snapPoints: snapPoints, stops: stops, clamp: clamp, nearest: nearest, velocityOf: velocityOf, next: next,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Sheet = api;
})(this);
