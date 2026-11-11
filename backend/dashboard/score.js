// The priority of a report: a suggestion made of four visible parts, never a decision.
// Plain functions without the page, so they can be tested with node (see tests/dashboard_score.test.js).
(function (root) {
  "use strict";

  // Points per part. The sum is the highest score. These are a first proposal, not a measured result.
  // TODO: the team confirms the weights.
  var DEFAULT_WEIGHTS = { hazard: 50, count: 20, age: 15, category: 15 };
  // How much a category matters, from 0 to 1 (a broken playground is more urgent than graffiti). Share of the category weight.
  var CATEGORY_IMPORTANCE = { playground_equipment: 1, pothole: 0.9, street_light: 0.8, tree: 0.7, litter: 0.35, graffiti: 0.2, other: 0 };
  var HIGH = 0.75; // share of the highest score
  var MEDIUM = 0.35;
  var COUNT_FULL = 5; // reports that give the full points for the number
  var AGE_FULL_DAYS = 15; // days that give the full points for the age

  function ageDays(report, now) {
    var created = Date.parse(report.created_at);
    if (isNaN(created)) return 0;
    return Math.max(0, (now - created) / 86400000);
  }

  function importance(category) {
    return Object.prototype.hasOwnProperty.call(CATEGORY_IMPORTANCE, category) ? CATEGORY_IMPORTANCE[category] : 0;
  }

  // The parts of the score of one report: [{key, label, points, max}], in the order they are shown
  function parts(report, weights, now) {
    var count = Math.max(1, report.reports_count || 1);
    return [
      { key: "hazard", label: "Gefahr", max: weights.hazard, points: report.lane === "hazard" ? weights.hazard : 0 },
      { key: "count", label: "Meldungen", max: weights.count, points: Math.min(1, count / COUNT_FULL) * weights.count },
      { key: "age", label: "Alter", max: weights.age, points: Math.min(1, ageDays(report, now) / AGE_FULL_DAYS) * weights.age },
      { key: "category", label: "Kategorie", max: weights.category, points: importance(report.category) * weights.category },
    ];
  }

  function score(report, weights, now) {
    return parts(report, weights, now).reduce(function (sum, part) { return sum + part.points; }, 0);
  }

  function maxScore(weights) {
    return weights.hazard + weights.count + weights.age + weights.category;
  }

  // "done" reports are no longer a priority
  function tier(report, weights, now) {
    if (report.status === "done") return "done";
    var max = maxScore(weights);
    if (max <= 0) return "low";
    var share = score(report, weights, now) / max;
    return share >= HIGH ? "high" : share >= MEDIUM ? "medium" : "low";
  }

  var api = { DEFAULT_WEIGHTS: DEFAULT_WEIGHTS, CATEGORY_IMPORTANCE: CATEGORY_IMPORTANCE, importance: importance, ageDays: ageDays, parts: parts, score: score, maxScore: maxScore, tier: tier };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Score = api;
})(this);
