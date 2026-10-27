// The names the reader shows for Lean declarations: a private declaration by the name its
// author wrote (#426), every other name as it is.
import assert from "node:assert/strict";
import { userName } from "../src/lib/names.js";

assert.equal(userName("_private.Shape.Expand.0.Shape.margin"), "Shape.margin");
assert.equal(userName("_private.Shape.Expand.0.Shape.half.eq_3"), "Shape.half.eq_3");
assert.equal(userName("_private.Main.0.margin"), "margin");
assert.equal(userName("Shape.margin"), "Shape.margin");
assert.equal(userName("Shape.steps.eq_1"), "Shape.steps.eq_1");
assert.equal(userName("Shape._private.0.x"), "Shape._private.0.x", "a private prefix comes first");
assert.equal(userName(undefined), undefined);
