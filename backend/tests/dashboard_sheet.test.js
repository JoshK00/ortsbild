// Run with: node --test tests/dashboard_sheet.test.js
const test = require("node:test");
const assert = require("node:assert");
const Sheet = require("../dashboard/sheet.js");

test("the three stops of a normal phone", () => {
  const points = Sheet.snapPoints(844, 107, 34);
  assert.strictEqual(points.peek, 222); // 188 + the safe area under the sheet
  assert.strictEqual(points.half, 422);
  assert.strictEqual(points.full, 737);
});

test("the stops stay apart on a phone on its side", () => {
  const points = Sheet.snapPoints(390, 60, 0);
  assert.ok(points.half - points.peek >= 60);
  assert.ok(points.full - points.half >= 60);
  assert.ok(points.peek < points.half && points.half < points.full);
});

test("a slow drag rests at the closest stop", () => {
  const list = Sheet.stops(Sheet.snapPoints(844, 107, 0), ["peek", "half", "full"]);
  assert.strictEqual(Sheet.nearest(200, 0, list), "peek");
  assert.strictEqual(Sheet.nearest(400, 0, list), "half");
  assert.strictEqual(Sheet.nearest(700, 0, list), "full");
});

test("a flick goes on to the next stop", () => {
  const list = Sheet.stops(Sheet.snapPoints(844, 107, 0), ["peek", "half", "full"]);
  assert.strictEqual(Sheet.nearest(188, 1.0, list), "half");
  assert.strictEqual(Sheet.nearest(188, 3.0, list), "full");
  assert.strictEqual(Sheet.nearest(422, -1.5, list), "peek");
});

test("the detail can be closed by dragging it down", () => {
  const list = Sheet.stops(Sheet.snapPoints(844, 107, 0), ["closed", "half", "full"]);
  assert.strictEqual(Sheet.nearest(150, 0, list), "closed");
  assert.strictEqual(Sheet.nearest(300, 0, list), "half");
  assert.strictEqual(Sheet.nearest(422, -1.2, list), "closed"); // a flick down
});

test("the speed comes from the last moments of the drag", () => {
  // the finger moves 100 px up in 100 ms: the sheet grows by 1 px per ms
  assert.strictEqual(Sheet.velocityOf([{ t: 0, y: 500 }, { t: 50, y: 450 }, { t: 100, y: 400 }]), 1);
  // an old slow part does not count
  assert.strictEqual(Sheet.velocityOf([{ t: 0, y: 500 }, { t: 350, y: 480 }, { t: 450, y: 480 }, { t: 500, y: 430 }]), 1);
  assert.strictEqual(Sheet.velocityOf([{ t: 0, y: 500 }]), 0);
  assert.strictEqual(Sheet.velocityOf([]), 0);
});

test("a tap goes to the next stop and from the biggest back to the smallest", () => {
  const names = ["peek", "half", "full"];
  assert.strictEqual(Sheet.next("peek", names), "half");
  assert.strictEqual(Sheet.next("half", names), "full");
  assert.strictEqual(Sheet.next("full", names), "peek");
  assert.strictEqual(Sheet.next("half", ["half", "full"]), "full");
  assert.strictEqual(Sheet.next("full", ["half", "full"]), "half");
});

test("clamp keeps a height inside its limits", () => {
  assert.strictEqual(Sheet.clamp(10, 100, 500), 100);
  assert.strictEqual(Sheet.clamp(900, 100, 500), 500);
  assert.strictEqual(Sheet.clamp(300, 100, 500), 300);
});
