"""A probe output that is cut short (a full disk, #194) ends the build with a `ProbeError` that
names the file, the line and the free space, never with a decoding traceback; the partial file
is kept on request. The probe flushes its output, fails when a write fails, and ends with a
`done` record that counts the bytes before it."""

import json
import os
import shutil
import subprocess

import pytest

from conftest import needs_lean
from prooflens.probe import KEEP_ENV, ProbeError, lean_session, parse_records

QUERY = {"scope_roots": [], "spec_prefix": "", "accept_prefix": "", "allowed_axioms": [],
         "requests": []}


def fake_lake(tmp_path, content: bytes):
    """A `lake` that writes `content` as the probe's output and exits 0, as Lean did on a full
    disk."""
    data = tmp_path / "content"
    data.write_bytes(content)
    lake = tmp_path / "lake"
    lake.write_text(f'#!/bin/sh\ncp "{data}" "$PROOFLENS_OUT"\n')
    lake.chmod(0o755)
    return str(lake)


def lines(*recs) -> bytes:
    return b"".join(json.dumps(r).encode() + b"\n" for r in recs)


def complete(*recs) -> bytes:
    body = lines(*recs)
    return body + lines({"record": "done", "bytes": len(body)})


ENV = {"record": "env", "lean": "4.0.0", "githash": "0"}
DECL = {"record": "defclosure", "name": "A.b", "closure": []}


def session(tmp_path, content: bytes):
    return lean_session(tmp_path, [], QUERY, parse_records, fake_lake(tmp_path, content),
                        work=tmp_path / "work")


def test_a_complete_output_is_read(tmp_path):
    res = session(tmp_path, complete(ENV, DECL))
    assert res["complete"] and res["defs"]["A.b"]["closure"] == []


@pytest.mark.parametrize("content, why", [
    # A record cut off after a `:`, as a failed write leaves it: what #194 met.
    (lines(ENV, DECL) + b'{"record": "decl", "name": "A.c", "type":', "line 3 is cut off"),
    (lines(ENV, DECL), "it ends at line 2, before its `done` record"),
    (b"", "it is empty"),
    # A record lost before `done`: the count of bytes does not match.
    (lines(ENV) + lines({"record": "done", "bytes": len(lines(ENV, DECL))}),
     "its `done` record (line 2) counts"),
])
def test_an_incomplete_output_is_a_probe_error(tmp_path, monkeypatch, content, why):
    monkeypatch.delenv(KEEP_ENV, raising=False)
    with pytest.raises(ProbeError) as e:
        session(tmp_path, content)
    msg = str(e.value)
    assert msg.startswith("the Lean probe's output is incomplete: ")
    assert "out.jsonl" in msg and why in msg
    assert "free" in msg and f"Set {KEEP_ENV}=1" in msg
    assert not e.value.deterministic


def test_a_record_that_does_not_decode_names_its_line(tmp_path):
    body = lines(ENV) + b'{"record": "decl", "name": \n' + lines(DECL)
    with pytest.raises(ProbeError) as e:
        session(tmp_path, body + lines({"record": "done", "bytes": len(body)}))
    assert "line 2 is not a complete record" in str(e.value)


def test_the_partial_output_is_kept_on_request(tmp_path, monkeypatch):
    monkeypatch.setenv(KEEP_ENV, "1")
    content = lines(ENV) + b'{"record": "decl", "na'
    with pytest.raises(ProbeError) as e:
        session(tmp_path, content)
    kept = [p for p in (tmp_path / "work").iterdir() if p.name.startswith("probe-output-")]
    assert len(kept) == 1 and kept[0].read_bytes() == content
    assert f"The partial output is kept at {kept[0]}." in str(e.value)


def lean_wrapper(tmp_path, toolchain, out=None):
    """A `lake` that runs `lean` of `toolchain` on the probe, with its output sent to `out`
    when given."""
    lake = tmp_path / "lake"
    redirect = f'PROOFLENS_OUT="{out}" ' if out else ""
    lake.write_text(f'#!/bin/sh\nshift\nshift\n{redirect}exec lean +{toolchain} "$@"\n')
    lake.chmod(0o755)
    return str(lake)


TOOLCHAINS = ["leanprover/lean4:v4.32.0", "leanprover/lean4:v4.24.0"]


def installed(toolchain):
    if shutil.which("elan") is None or toolchain not in subprocess.run(
            ["elan", "toolchain", "list"], capture_output=True, text=True).stdout:
        pytest.skip(f"{toolchain} is not installed")


@needs_lean
@pytest.mark.parametrize("toolchain", TOOLCHAINS)
def test_the_probe_counts_its_bytes_and_fails_when_a_write_fails(tmp_path, toolchain):
    installed(toolchain)
    recs = lean_session(tmp_path, [], QUERY, list, lean_wrapper(tmp_path, toolchain))
    done = json.loads(recs[-1])
    assert done["record"] == "done"
    assert done["bytes"] == sum(len(r.encode()) for r in recs[:-1])

    if not os.path.exists("/dev/full"):
        pytest.skip("no /dev/full")
    with pytest.raises(ProbeError) as e:
        lean_session(tmp_path, [], QUERY, list, lean_wrapper(tmp_path, toolchain, "/dev/full"))
    assert "the Lean probe failed (1)" in str(e.value)
    assert "space" in str(e.value).lower()
    # Another attempt, with space, may succeed: the failure is not recorded as the module's.
    assert not e.value.deterministic
