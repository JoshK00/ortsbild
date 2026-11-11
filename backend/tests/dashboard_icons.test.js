// Run with: node --test tests/dashboard_icons.test.js
const test = require("node:test");
const assert = require("node:assert");
const Icons = require("../dashboard/icons.js");

const CATEGORIES = ["litter", "graffiti", "street_light", "playground_equipment", "pothole", "tree", "other"]; // classification/models.py

test("every category of the classification has an icon", () => {
  for (const category of CATEGORIES) {
    const icon = Icons.ICONS[category];
    assert.ok(icon && icon.paths.length > 0 && icon.paths.every((d) => /^M/.test(d)), category);
  }
});

test("a category that is unknown gets the icon of other", () => {
  assert.strictEqual(Icons.known("something new"), "other");
  assert.strictEqual(Icons.known("constructor"), "other"); // not a hole in the lookup
  assert.strictEqual(Icons.known("pothole"), "pothole");
});

test("every category of the backend has an icon", () => {
  for (const category of ["litter", "graffiti", "street_light", "playground_equipment", "pothole", "tree", "other"]) {
    assert.strictEqual(Icons.known(category), category);
  }
});

test("the icon of the photo placeholder exists", () => {
  assert.ok(Icons.UI.photo.paths.length > 0 && /^M/.test(Icons.UI.photo.paths[0]));
});
