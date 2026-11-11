// The search of the dashboard, the parts that need no page (so node can test them, see tests/dashboard_search.test.js):
// which of the loaded cases match what was typed, and a check of what the server answers for places and addresses.
(function (root) {
  "use strict";

  var MIN_PLACE_CHARS = 3; // the server refuses shorter texts
  var MAX_CASES = 5;
  var MAX_PLACES = 5;

  // Small letters without accents, "ß" as "ss": "Straße" is found by "strasse", "Münster" by "munster"
  function fold(text) {
    return String(text === null || text === undefined ? "" : text).toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/ß/g, "ss");
  }

  // What was typed as words. Every word has to be in the case (address, category name or text), in any order.
  function words(query) {
    return fold(query).split(/[\s,]+/).filter(function (word) { return word.length > 0; });
  }

  // The cases that match, in the order they come (the caller passes them ranked). `nameOf` turns a category into its German name.
  function matchCases(cases, query, nameOf) {
    var wanted = words(query);
    if (!wanted.length) return [];
    return cases.filter(function (report) {
      var haystack = fold([report.address, nameOf(report.category), report.text].join(" "));
      return wanted.every(function (word) { return haystack.indexOf(word) >= 0; });
    }).slice(0, MAX_CASES);
  }

  // What the server answered for a place search: {"results": [{"label", "lat", "lon"}]}. Anything that does not fit is dropped,
  // the page never shows or uses a value it did not check.
  function parseResults(body) {
    var list = body && Array.isArray(body.results) ? body.results : [];
    return list.filter(function (entry) {
      return entry && typeof entry.label === "string" && entry.label.length > 0 && entry.label.length <= 200
        && typeof entry.lat === "number" && typeof entry.lon === "number"
        && entry.lat >= -90 && entry.lat <= 90 && entry.lon >= -180 && entry.lon <= 180;
    }).slice(0, MAX_PLACES).map(function (entry) { return { label: entry.label, lat: entry.lat, lon: entry.lon }; });
  }

  var api = { MIN_PLACE_CHARS: MIN_PLACE_CHARS, fold: fold, words: words, matchCases: matchCases, parseResults: parseResults };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Search = api;
})(this);
