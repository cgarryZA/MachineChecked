"""An author's account kept in the project's readings ledger, shown at step 3 by declaration
(#627): the rows that name the unit's declaration exactly, each with its source and digest,
which the report records; a unit no row names says so; and nothing of the ledger in the read
and compare steps. The site is the synthetic one of `test_review_withholds_outcome.py`; nothing
here builds Lean."""

import json

from prooflens import review_cli as rc
from prooflens.util import sha256_text
from test_review_withholds_outcome import (FIXED_SPEC, FIXED_UNIT, SPEC, TEXTS, UNIT,
                                           write_spec_site)

WHO = rc.parse_reviewer("human:Ledger-Reviewer")
ACCOUNT = "AUTHOR-LEDGER: the proposition is false at n = 0, as Remark 3 says."
ROWS = [{"id": "R1", "text": ACCOUNT, "declarations": [SPEC], "read_at": "abc123"},
        # A namespace alone, or another declaration, is no association.
        {"id": "R2", "text": "AUTHOR-OTHER: about the namespace.", "declarations": ["Syn"],
         "namespaces": ["Syn.PaperSpec"], "read_at": "abc123"},
        {"id": "R3", "text": "AUTHOR-ELSEWHERE.", "declarations": ["Syn.other"]}]


def session(tmp_path, rows=ROWS, ledger_name="readings.json"):
    work = write_spec_site(tmp_path).parent.parent
    ledger = tmp_path / ledger_name
    if rows is not None:
        ledger.write_text(json.dumps({"rows": rows}))
    return rc.Session(work, WHO, ledger=ledger, ledger_base=tmp_path)


def to_author(s, uid, verdict="faithful"):
    shown = [s.read(uid), json.dumps(s.read(uid, as_json=True))]
    s.lock(uid, TEXTS["reading.md"])
    shown += [s.show(uid), json.dumps(s.show(uid, as_json=True))]
    for text in shown:
        assert "AUTHOR-" not in text and "readings.json" not in text and "ledger" not in text
    s.decide(uid, verdict, TEXTS["comparison.md"])


def test_step_3_shows_the_rows_that_name_the_declaration_and_the_report_records_them(tmp_path):
    s = session(tmp_path)
    to_author(s, UNIT)
    text = s.author(UNIT)
    digest = sha256_text(json.dumps(ROWS[0], sort_keys=True, ensure_ascii=False))
    assert (f"The author's account in the readings ledger, row R1 (readings.json#R1, read at "
            f"abc123; digest {digest[:12]}), on {SPEC}:\n{ACCOUNT}") in text
    assert "AUTHOR-OTHER" not in text and "AUTHOR-ELSEWHERE" not in text
    # What the verdict means for the claim stays the step's last word (#685).
    assert text.rstrip().endswith("so no proof of the proposition can follow.")
    pk = s.author(UNIT, as_json=True)
    keys = list(pk["interpretations"])
    assert keys.index("ledger") < keys.index("refuted_by")
    (row,) = pk["interpretations"]["ledger"]["rows"]
    assert (row["source"], row["sha256"], row["text"]) == ("readings.json#R1", digest, ACCOUNT)
    r = s.submit(UNIT, "none")
    assert r["author_review"]["accounts"] == [{"source": "readings.json#R1", "sha256": digest}]
    # Undo keeps what was shown.
    assert s.undo()["author_accounts"] == r["author_review"]["accounts"]


def test_a_unit_no_row_names_says_so(tmp_path):
    s = session(tmp_path)
    to_author(s, FIXED_UNIT, "faithful to the correction")
    assert f"No row of the readings ledger (readings.json) names {FIXED_SPEC}." in \
        s.author(FIXED_UNIT)
    assert s.author(FIXED_UNIT, as_json=True)["interpretations"]["ledger"]["rows"] == []
    r = s.submit(FIXED_UNIT, "none")
    assert "accounts" not in r["author_review"]


def test_an_unreadable_ledger_is_named_and_no_ledger_adds_nothing(tmp_path):
    s = session(tmp_path, rows=None)
    to_author(s, UNIT)
    assert "The readings ledger (readings.json) could not be read: the file does not exist." \
        in s.author(UNIT)
    plain = rc.Session(write_spec_site(tmp_path / "plain").parent.parent, WHO)
    to_author(plain, UNIT)
    assert "readings ledger" not in plain.author(UNIT)
    assert "ledger" not in plain.author(UNIT, as_json=True).get("interpretations", {})
