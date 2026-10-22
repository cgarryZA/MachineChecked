"""#213: a name a module docstring or a review cites may be declared in a module the probe did
not load (another module of the library, or a dependency's). It is looked up in the Lean
sources of the project and its Lake packages before it is reported, and a dependency's own
docstrings are left to its audit."""

from prooflens.review_citations import unresolved
from prooflens.source_names import declarations, undeclared_doc_names

EXTRA = """/-! Lemmas no audited module imports: `Base.Extra.gone` is mentioned in a comment. -/
namespace Base.Extra

/-- A docstring that mentions `theorem not_this`. -/
theorem lemma_x : True := trivial

section Inner
-- def commented_out : Nat := 0
private def helper : Nat := 1
end Inner

instance (priority := 50) instShow : Inhabited Nat := ⟨0⟩

end Base.Extra

theorem _root_.Other.rooted : True := trivial

namespace Base
structure Data where
  x : Nat
end Base
"""


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_declarations_track_namespaces_and_skip_comments():
    names, entered = declarations(EXTRA)
    assert names == {"Base.Extra.lemma_x", "Base.Extra.helper", "Base.Extra.instShow",
                     "Other.rooted", "Base.Data"}
    assert entered == {"Base", "Base.Extra"}


def cite(token):
    return {"file": "review.md", "line": 1, "kind": "name", "token": token}


def test_a_review_citation_resolves_in_a_dependency_the_probe_did_not_load(tmp_path):
    write(tmp_path / ".lake" / "packages" / "base" / "Base" / "Extra.lean", EXTRA)
    tokens = ["Base.Extra.lemma_x", "Extra.lemma_x", "lemma_x", "Base.Extra", "Base.Data",
              "Base.Extra.gone", "not_this", "commented_out"]
    names = {"checked": tokens, "unresolved": tokens}
    left = [c["token"] for c in unresolved([cite(t) for t in tokens], names, [tmp_path])]
    # Mentions in comments and docstrings declare nothing.
    assert left == ["Base.Extra.gone", "not_this", "commented_out"]


def doc(module, name):
    return {"module": module, "file": module.replace(".", "/") + ".lean", "line": 3,
            "name": name, "heading": ""}


def test_docstring_names_resolve_in_the_sources_and_dependencies_are_left_out(tmp_path):
    write(tmp_path / "Lib" / "A.lean", "/-! The data is built by `Lib.Data.ofSolves`. -/\n"
          "namespace Lib\ntheorem a : True := trivial\nend Lib\n")
    write(tmp_path / "Lib" / "B.lean", "namespace Lib.Data\ndef ofSolves : Nat := 0\nend Lib.Data\n")
    write(tmp_path / ".lake" / "packages" / "base" / "Base" / "Extra.lean", EXTRA)
    docs = [doc("Lib.A", "Lib.Data.ofSolves"),   # another module of the library, not loaded
            doc("Lib.A", "Data.ofSolves"),       # inside the namespace the file enters
            doc("Lib.A", "Base.Extra.lemma_x"),  # a dependency's module, not loaded
            doc("Lib.A", "Lib.Data.gone"),
            doc("Base.Extra", "Base.Extra.gone")]  # a dependency's own docstring
    assert [(d["module"], d["name"]) for d in undeclared_doc_names(docs, tmp_path)] == [
        ("Lib.A", "Lib.Data.gone")]
