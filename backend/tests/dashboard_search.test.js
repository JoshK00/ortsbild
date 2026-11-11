const test = require("node:test");
const assert = require("node:assert");
const Search = require("../dashboard/search.js");

const names = { pothole: "Schlagloch", graffiti: "Graffiti", playground_equipment: "Spielgerät" };
const nameOf = (key) => names[key] || "Sonstiges";
const cases = [
  { id: "a", category: "pothole", address: "Botnanger Straße, 70193 Stuttgart", text: "Tiefes Loch am Fahrbahnrand" },
  { id: "b", category: "playground_equipment", address: "Sommerhaldestraße 20, 70195 Stuttgart", text: "Die Wippe ist durchgebrochen" },
  { id: "c", category: "graffiti", address: "Eltinger Straße 87, 70195 Stuttgart", text: null },
];

test("a case is found by a part of the address, the category or the text, without caring for accents or capitals", () => {
  assert.deepStrictEqual(Search.matchCases(cases, "botnanger strasse", nameOf).map((c) => c.id), ["a"]);
  assert.deepStrictEqual(Search.matchCases(cases, "SPIELGERAT", nameOf).map((c) => c.id), ["b"]);
  assert.deepStrictEqual(Search.matchCases(cases, "wippe", nameOf).map((c) => c.id), ["b"]);
  assert.deepStrictEqual(Search.matchCases(cases, "70195", nameOf).map((c) => c.id), ["b", "c"]);
});

test("every word has to match, in any order", () => {
  assert.deepStrictEqual(Search.matchCases(cases, "stuttgart eltinger", nameOf).map((c) => c.id), ["c"]);
  assert.deepStrictEqual(Search.matchCases(cases, "eltinger wippe", nameOf), []);
});

test("an empty or blank search matches nothing, a missing text does not break it", () => {
  assert.deepStrictEqual(Search.matchCases(cases, "", nameOf), []);
  assert.deepStrictEqual(Search.matchCases(cases, "  , ", nameOf), []);
  assert.strictEqual(Search.matchCases([{ id: "x", category: "other" }], "nichts", nameOf).length, 0);
});

test("at most five cases come back, in the order they were given", () => {
  const many = Array.from({ length: 9 }, (_, i) => ({ id: String(i), category: "pothole", address: "Teststraße " + i }));
  assert.deepStrictEqual(Search.matchCases(many, "teststrasse", nameOf).map((c) => c.id), ["0", "1", "2", "3", "4"]);
});

test("the answer of the server is checked before the page uses it", () => {
  const good = { label: "Königstraße 1, 70173 Stuttgart", lat: 48.78, lon: 9.18 };
  assert.deepStrictEqual(Search.parseResults({ results: [good] }), [good]);
  const bad = [
    { label: "", lat: 1, lon: 1 }, { label: "x", lat: "48", lon: 9 }, { label: "x", lat: 91, lon: 9 },
    { label: "x", lat: 1, lon: 181 }, { label: "y".repeat(201), lat: 1, lon: 1 }, null, "text",
  ];
  assert.deepStrictEqual(Search.parseResults({ results: bad }), []);
  assert.deepStrictEqual(Search.parseResults(null), []);
  assert.deepStrictEqual(Search.parseResults({ results: "nope" }), []);
  assert.strictEqual(Search.parseResults({ results: Array.from({ length: 9 }, () => good) }).length, 5);
});

test("a place is searched from three characters on", () => {
  assert.strictEqual(Search.MIN_PLACE_CHARS, 3);
});
