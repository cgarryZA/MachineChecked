// The name of a Lean declaration as its author wrote it. Lean keeps a private declaration under
// a name of its own, `_private`, the module and `0` before the written name
// (`_private.Shape.Expand.0.Shape.margin` for `Shape.margin`); records name it so, and the
// reader shows the written name (Lean's `privateToUserName`). Other names are shown as they are.
export function userName(name) {
  const m = /^_private\.(?:[^.]+\.)+?0\.(.+)$/.exec(name ?? "");
  return m ? m[1] : name;
}
