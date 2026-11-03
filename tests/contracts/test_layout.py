"""Where a Lake package keeps its modules' sources (#535): the library's source folder, the
package's `srcDir` joined with the library's own, read from `lakefile.toml` or `lakefile.lean`.
In the default layout every module is where it always was, `A/B/C.lean` in the project."""

import subprocess

from prooflens import audit
from prooflens.layout import library_files, module_file, module_of, source_dirs
from prooflens.source_names import lean_files


def write(path, text=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_the_default_layout_is_unchanged(tmp_path):
    write(tmp_path / "lakefile.toml", 'name = "lib"\n[[lean_lib]]\nname = "Lib"\n')
    write(tmp_path / "Lib" / "Main.lean")
    assert module_file(tmp_path, "Lib.Main") == "Lib/Main.lean"
    assert module_file(tmp_path, "Lib.Absent") == "Lib/Absent.lean"
    assert module_file(None, "Lib.Main") == "Lib/Main.lean"
    assert module_of(tmp_path, "Lib/Main.lean") == "Lib.Main"
    assert [(f.name, rel.as_posix()) for f, rel in library_files(tmp_path, "Lib")] == [
        ("Main.lean", "Lib/Main.lean")]
    # Without a lakefile, too.
    assert module_file(tmp_path / "none", "A.B") == "A/B.lean"


def test_a_toml_lakefile_sets_the_package_and_library_folders(tmp_path):
    write(tmp_path / "lakefile.toml",
          'name = "lib"\nsrcDir = "pkg"\n\n[[lean_lib]]\nname = "Lib"\nsrcDir = "./src/"\n\n'
          '[[lean_lib]]\nname = "Other"\nroots = ["Other", "More"]\n')
    assert source_dirs(tmp_path) == [(frozenset({"Lib"}), "pkg/src"),
                                     (frozenset({"Other", "More"}), "pkg"), (frozenset(), "pkg")]
    write(tmp_path / "pkg" / "src" / "Lib.lean")
    write(tmp_path / "pkg" / "src" / "Lib" / "Main.lean")
    assert module_file(tmp_path, "Lib.Main") == "pkg/src/Lib/Main.lean"
    # A module of no library is looked for in the package's folder.
    assert module_file(tmp_path, "More.X") == "pkg/More/X.lean"
    assert module_file(tmp_path, "Zed.Y") == "pkg/Zed/Y.lean"
    assert module_of(tmp_path, "pkg/src/Lib/Main.lean") == "Lib.Main"
    assert module_of(tmp_path, "pkg/More/X.lean") == "More.X"
    assert [rel.as_posix() for _, rel in library_files(tmp_path, "Lib")] == [
        "Lib.lean", "Lib/Main.lean"]


def test_a_lean_lakefile_sets_them_with_string_literals(tmp_path):
    write(tmp_path / "lakefile.lean", '''import Lake
open Lake DSL

package «my-pkg» where
  -- srcDir := "commented"
  version := v!"0.1"

/- lean_lib Ghost where
  srcDir := "ghost" -/

@[default_target]
lean_lib «Lib» where
  srcDir := "src" / "lean"
  roots := #[`Lib, `Extra]

lean_lib Plain

lean_exe tool where
  root := `Main
''')
    assert source_dirs(tmp_path) == [(frozenset({"Lib", "Extra"}), "src/lean"),
                                     (frozenset({"Plain"}), "."), (frozenset(), ".")]
    assert module_file(tmp_path, "Extra.A") == "src/lean/Extra/A.lean"
    assert module_file(tmp_path, "Plain.A") == "Plain/A.lean"
    # Lake reads `lakefile.lean` when both are present.
    write(tmp_path / "lakefile.toml", 'name = "x"\nsrcDir = "elsewhere"\n')
    assert source_dirs(tmp_path)[0] == (frozenset({"Lib", "Extra"}), "src/lean")


def test_a_package_dependency_is_read_in_its_own_source_folder(tmp_path):
    pkg = tmp_path / ".lake" / "packages" / "dep"
    write(pkg / "lakefile.toml", 'name = "dep"\n[[lean_lib]]\nname = "Dep"\nsrcDir = "src"\n')
    write(pkg / "src" / "Dep" / "Basic.lean")
    write(tmp_path / "lakefile.toml", 'name = "lib"\n[[lean_lib]]\nname = "Lib"\n')
    write(tmp_path / "Lib" / "Main.lean")
    assert sorted(m for _, m in lean_files([tmp_path])) == ["Dep.Basic", "Lib.Main"]


def test_source_links_point_into_the_source_folder(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    write(tmp_path / "lakefile.toml", 'name = "lib"\n[[lean_lib]]\nname = "Lib"\n\n'
                                      '[[lean_lib]]\nname = "Aux"\n')
    write(tmp_path / "Lib" / "Main.lean")
    write(tmp_path / "Aux.lean")
    info = audit.source_info(tmp_path, ["Lib", "Aux"], "owner/repo")
    assert (info["source_prefix"], info["source_roots"]) == ("", ["Aux", "Lib"])
    assert audit.source_path(tmp_path, "Lib.Main") == "Lib/Main.lean"

    other = tmp_path / "other"
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    write(other / "lakefile.toml", 'name = "lib"\nsrcDir = "src"\n[[lean_lib]]\nname = "Lib"\n\n'
                                   '[[lean_lib]]\nname = "Aux"\nsrcDir = "aux"\n')
    write(other / "src" / "Lib" / "Main.lean")
    write(other / "src" / "aux" / "Aux.lean")
    info = audit.source_info(other, ["Lib", "Aux"], "owner/repo")
    # One prefix serves every link: the roots in another folder get none rather than a wrong one.
    assert (info["source_prefix"], info["source_roots"]) == ("src/", ["Lib"])
    assert audit.source_path(other, "Lib.Main") == "src/Lib/Main.lean"
    assert audit.source_path(other, "Aux") == "src/aux/Aux.lean"
