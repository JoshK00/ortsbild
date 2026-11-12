// Run with: node --test tests/dashboard_score.test.js
const test = require("node:test");
const assert = require("node:assert");
const Score = require("../dashboard/score.js");

const NOW = Date.parse("2026-11-09T12:00:00Z");
const daysAgo = (days) => new Date(NOW - days * 86400000).toISOString();
const base = { category: "litter", lane: "nuisance", status: "received", reports_count: 1, created_at: daysAgo(0) };

test("a fresh nuisance scores the first vote and the small importance of litter", () => {
  const points = Score.score(base, Score.DEFAULT_WEIGHTS, NOW);
  assert.strictEqual(points, 9.25); // 1 of 5 votes gives 4 of 20 points, litter is 0.35 of 15 points
  assert.strictEqual(Score.tier(base, Score.DEFAULT_WEIGHTS, NOW), "low");
});

test("a hazard on a safety category with several reports is high", () => {
  const report = { ...base, category: "pothole", lane: "hazard", reports_count: 5, created_at: daysAgo(15) };
  assert.strictEqual(Score.score(report, Score.DEFAULT_WEIGHTS, NOW), 98.5); // 50 + 20 + 15 + 0.9 * 15
  assert.strictEqual(Score.tier(report, Score.DEFAULT_WEIGHTS, NOW), "high");
});

test("count and age are capped", () => {
  const report = { ...base, reports_count: 50, created_at: daysAgo(400) };
  const [, count, age] = Score.parts(report, Score.DEFAULT_WEIGHTS, NOW);
  assert.strictEqual(count.points, 20);
  assert.strictEqual(age.points, 15);
});

test("the parts add up to the score", () => {
  const report = { ...base, category: "tree", lane: "hazard", reports_count: 2, created_at: daysAgo(3) };
  const sum = Score.parts(report, Score.DEFAULT_WEIGHTS, NOW).reduce((total, part) => total + part.points, 0);
  assert.strictEqual(sum, Score.score(report, Score.DEFAULT_WEIGHTS, NOW));
});

test("a done report is no priority, whatever its score", () => {
  const report = { ...base, category: "pothole", lane: "hazard", reports_count: 5, status: "done" };
  assert.strictEqual(Score.tier(report, Score.DEFAULT_WEIGHTS, NOW), "done");
});

test("the tiers follow the weights: without any weight nothing is above low", () => {
  const none = { hazard: 0, count: 0, age: 0, category: 0 };
  const report = { ...base, category: "pothole", lane: "hazard", reports_count: 5 };
  assert.strictEqual(Score.tier(report, none, NOW), "low");
});

test("a hazard weight of zero removes the hazard from the ranking", () => {
  const weights = { ...Score.DEFAULT_WEIGHTS, hazard: 0 };
  const hazard = { ...base, lane: "hazard" };
  assert.strictEqual(Score.score(hazard, weights, NOW), Score.score(base, weights, NOW));
});

test("a date that cannot be read counts as new, it does not break the list", () => {
  const report = { ...base, created_at: "not a date" };
  assert.strictEqual(Score.ageDays(report, NOW), 0);
});

test("a broken playground matters more than graffiti, and an unknown category matters least", () => {
  const playground = { ...base, category: "playground_equipment" };
  const graffiti = { ...base, category: "graffiti" };
  const unknown = { ...base, category: "constructor" };
  const [a, b, c] = [playground, graffiti, unknown].map((r) => Score.score(r, Score.DEFAULT_WEIGHTS, NOW));
  assert.ok(a > b && b > c);
  assert.strictEqual(c, Score.score({ ...base, category: "other" }, Score.DEFAULT_WEIGHTS, NOW));
});

test("every vote raises the priority up to five, then it stays", () => {
  const scores = [1, 2, 3, 5, 9].map((n) => Score.score({ ...base, reports_count: n }, Score.DEFAULT_WEIGHTS, NOW));
  assert.ok(scores[0] < scores[1] && scores[1] < scores[2] && scores[2] < scores[3]);
  assert.strictEqual(scores[3], scores[4]);
});

test("the parts of the priority have German names", () => {
  const labels = Score.parts(base, Score.DEFAULT_WEIGHTS, NOW).map((part) => part.label);
  assert.deepStrictEqual(labels, ["Gefahr", "Meldungen", "Alter", "Kategorie"]);
});
