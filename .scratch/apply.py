"""Apply the reviewed status-code changes to the fixed PR87 base, without carrying this helper."""
from pathlib import Path
import json
import shutil
import sys

root = Path.cwd()
src = Path(__file__).parent / "new"
for name, dest in {
    "status.py": "engine/python/prooflens/status.py",
    "status.js": "web/src/lib/status.js",
    "test_status_codes.py": "tests/contracts/test_status_codes.py",
    "status.test.mjs": "web/tests/status.test.mjs",
    "STATUS_PRESENTATION.md": "docs/STATUS_PRESENTATION.md",
}.items():
    assert not (root / dest).exists(), dest
    shutil.copyfile(src / name, root / dest)

def edit(name, transform):
    p = root / name
    old = p.read_text()
    new = transform(old)
    assert old != new, name
    p.write_text(new)


def assessor(s):
    s = s.replace('OUT_OF_SCOPE = {"expository", "literature", "empirical", "proof-step", "part-of", "duplicate"}', 'from .status import OUT_OF_SCOPE, claim_code, result as status_result')
    a = s.index('    @staticmethod\n    def claim_status'); b = s.index('    def blockers(', a)
    s = s[:a] + s[b:]
    s = s.replace('def blockers(self, claim: dict, status: str, clauses: list[dict])', 'def blockers(self, claim: dict, clauses: list[dict])')
    s = s.replace('if status.startswith("definition") and status != "definition: reviewed" and not out:', 'if claim["scope"] == "definition" and claim_code(claim, clauses) != "definition.reviewed" and not out:')
    s = s.replace('status = self.claim_status(c, clauses)\n            claims.append({"id": c["id"], "status": status, "clauses": clauses,\n                           "blockers": self.blockers(c, status, clauses)})', 'state = status_result(claim_code(c, clauses))\n            claims.append({"id": c["id"], **state, "clauses": clauses,\n                           "blockers": self.blockers(c, clauses)})')
    s = s.replace('if r["status"] != "definition: reviewed":', 'if claim_code(e, r["clauses"]) != "definition.reviewed":')
    s = s.replace('if r["status"] != "formal: accepted":', 'if claim_code(e, r["clauses"]) != "formal.accepted":')
    return s
edit('engine/python/prooflens/assess.py', assessor)


def manifest(s):
    s = s.replace('from .source_regions', 'from .status import claim_code, result as status_result\nfrom .source_regions', 1)
    a = s.index('def status_class('); b = s.index('def top_of(', a); s = s[:a] + s[b:]
    s = s.replace('a = assessed[c["id"]]\n', 'a = assessed[c["id"]]\n        state = {**status_result(claim_code(c, a["clauses"])), "status": a["status"]}\n')
    s = s.replace('"scope": c["scope"], "status": a["status"], "class": status_class(a["status"]),', '"scope": c["scope"], **state,')
    s = s.replace('"source_sha256": c.get("source_sha256"), "status": a["status"],\n            "class": status_class(a["status"]),', '"source_sha256": c.get("source_sha256"), **state,')
    s = s.replace('"classes": {st: status_class(st) for s in summary.values() for st in s},', '"classes": {c["status"]: c["class"] for c in index_claims},')
    s = s.replace('"status": c["status"],\n                       "statement"', '"status": c["status"], "status_code": c["status_code"],\n                       "statement"')
    return s
edit('engine/python/prooflens/manifest.py', manifest)


def simple(s):
    s = s.replace('from .sources import acquire', 'from .sources import acquire\nfrom .status import result as status_result')
    for name in ('module', 'm'):
        s = s.replace('return None, f"linked: Lean not checked (its module {' + name + '} is not built)"', 'return None, status_result("link.module-unbuilt", module=' + name + ')')
        s = s.replace('return None, f"linked: Lean not checked (its module {' + name + '} could not be loaded)"', 'return None, status_result("link.module-failed", module=' + name + ')')
    s = s.replace('return None, f"linked: Lean name is ambiguous (declared in {mods})"', 'return None, status_result("link.ambiguous", modules=mods)')
    s = s.replace('failed: dict) -> tuple[dict | None, str | None]:', 'failed: dict) -> tuple[dict | None, dict | None]:')
    s = s.replace('def link_state(rec: dict | None) -> tuple[str, str]:', 'def link_state(rec: dict | None) -> dict:')
    s = s.replace('"""The status of a confirmed link from its probe record, and its class."""', '"""Code, label and colour selected from the probe result, not its displayed words."""')
    for old, code in [('\"linked: Lean declaration not found\", \"malformed\"', 'link.missing'), ('\"linked: Lean definition\", \"proved\"', 'link.definition'), ('\"linked: Lean proof incomplete (sorry)\", \"open\"', 'link.incomplete'), ('\"linked: Lean proof uses further axioms\", \"open\"', 'link.axioms'), ('\"linked: Lean proof checked\", \"proved\"', 'link.checked')]:
        s = s.replace('return ' + old, 'return status_result("' + code + '")')
    s = s.replace('    if rec.get("kind") != "theorem":\n        return status_result("link.definition")', '    if not rec.get("kind") or any(not e.startswith("axioms=") for e in rec.get("errors", [])):\n        return status_result("link.failed")\n    if rec.get("kind") != "theorem":\n        return status_result("link.definition")')
    s = s.replace('status, cls = "linked: Lean not checked (the project is not built)", "unspecified"', 'state = status_result("link.unbuilt")')
    s = s.replace('status, cls = (why, "unspecified") if why else link_state(rec)', 'state = why or link_state(rec)')
    s = s.replace('{"name": n, "status": status, "class": cls,', '{"name": n, **state,')
    s = s.replace('c["status"], c["class"] = worst["status"], worst["class"]', 'c.update({k: worst[k] for k in ("status", "status_code", "class")})')
    s = s.replace('c["status"], c["class"] = "suggested link, not confirmed", "unspecified"', 'c.update(status_result("link.suggested"))')
    s = s.replace('c["status"], c["class"] = "not linked", "unspecified"', 'c.update(status_result("link.none"))')
    s = s.replace('"status": c["status"], "class": c["class"],', '"status": c["status"], "status_code": c["status_code"], "class": c["class"],')
    s = s.replace('"name": l["name"], "status": l.get("status"), "class": l.get("class"),', '"name": l["name"], "status": l.get("status"), "status_code": l.get("status_code", "link.suggested"), "class": l.get("class"),')
    return s
edit('engine/python/prooflens/simple.py', simple)


def paper(s):
    s = s.replace('from .util import content_id', 'from .util import content_id\nfrom .status import result as status_result')
    s = s.replace('NOT_CHECKED = "linked: Lean not checked here (no audit published)"', 'NOT_CHECKED = status_result("link.no-audit")["status"]')
    s = s.replace('NOT_IN_AUDIT = "linked: Lean not checked here (the published audit does not list it)"', 'NOT_IN_AUDIT = status_result("link.not-in-audit")["status"]')
    s = s.replace('NOT_LINKED = "not linked"', 'NOT_LINKED = status_result("link.none")["status"]')
    a = s.index('def _state('); b = s.index('def write_paper_site(', a)
    s = s[:a] + '''def _state(links: list[dict], audit: dict | None = None, audited: bool = False) -> dict:
    """Published status is attributed data, not a local proof inferred from its wording."""
    if audit:
        return {"status": audit["status"], "class": audit["class"], "status_code": "published-audit"}
    return status_result("link.none" if not links else "link.not-in-audit" if audited else "link.no-audit")


''' + s[b:]
    s = s.replace('status, cls = _state(', 'state = _state(')
    s = s.replace('{"status": status, "class": cls,', '{**state,')
    s = s.replace('"status": status, "class": cls, "by_project": by_project}', '**state, "by_project": by_project}')
    s = s.replace('**_link_state(l, audits.get(l["repository"]),', '**_state([l], audits.get(l["repository"]),')
    return s
edit('engine/python/prooflens/paper.py', paper)
edit('engine/python/prooflens/export.py', lambda s: s.replace('"scope_note", "scope_reviewed", "status", "class",', '"scope_note", "scope_reviewed", "status", "status_code", "class",'))
edit('engine/python/prooflens/cli.py', lambda s: s.replace('"status": c["status"], "class": c["class"]', '"status": c["status"], "status_code": c["status_code"], "class": c["class"]').replace('"status": l["status"], "class": l["class"]', '"status": l["status"], "status_code": l["status_code"], "class": l["class"]'))


def passport(s):
    s = s.replace('  import { tick } from "svelte";', '  import { tick } from "svelte";\n  import { clauseVerdict as verdict, clauseNote, linkVerdict, inScope } from "../lib/status.js";')
    a = s.index('  // A sentence under a clause'); b = s.index('  let copied =', a)
    s = s[:a] + '  const note = (cl) => clauseNote(cl, claim.clauses.length);\n' + s[b:]
    a = s.index('  // The sentence under a link'); b = s.index('  // A check or piece of evidence', a); s = s[:a] + s[b:]
    return s.replace('claim.scope !== "out-of-scope" && !String(claim.status).startsWith("out of scope")', 'inScope(claim)')
edit('web/src/components/Passport.svelte', passport)
edit('web/src/components/Reader.svelte', lambda s: s.replace('  import { projectClaims }', '  import { inScope } from "../lib/status.js";\n  import { projectClaims }').replace('  const inScope = (c) => !String(c.status).startsWith("out of scope");\n', ''))
edit('web/src/components/Coverage.svelte', lambda s: s.replace('import { CLASS_ORDER, notProved }', 'import { CLASS_ORDER }').replace('  let { index }', '  import { notAccepted } from "../lib/status.js";\n\n  let { index }').replace('notProved)', 'notAccepted)'))


def data(s):
    s = s.replace('{ status: "not linked", class: "unspecified" }', '{ status_code: "link.none", status: "not linked", class: "unspecified" }')
    s = s.replace('status: st.status, class: st.class, audit:', 'status: st.status, status_code: st.status_code, class: st.class, audit:')
    a = s.index('// A claim is "not proved"'); b = s.index('// The review queue', a)
    return s[:a] + s[b:]
edit('web/src/lib/data.js', data)
edit('web/tests/reader.test.mjs', lambda s: s.replace('import { chromium }', 'import "./status.test.mjs";\nimport { chromium }'))


def toy(s):
    a = s.index('def test_status_classes_are_total():'); b = s.index('\n\n@needs_lean', a)
    return s[:a] + '''def test_status_classes_are_total():
    from prooflens.status import LABELS, result
    for code in LABELS:
        state = result(code, module="Synthetic", modules="Synthetic.One, Synthetic.Two")
        assert state["status_code"] == code
        assert state["class"] in {"accepted", "proved", "refuted", "open", "malformed",
                                  "out-of-scope", "unspecified", "declared"}
''' + s[b:]
edit('tests/contracts/test_toy.py', toy)
edit('tests/contracts/test_pdf_inventory.py', lambda s: s.replace('"clauses": [{"accept": "Synthetic.proof"}]', '"clauses": [{"name": "main", "accept": "Synthetic.proof", "accept_ok": True, "state": "proved", "review": "reviewed"}]'))
edit('tests/simple/test_audit.py', lambda s: s.replace('    from prooflens import simple\n    import inspect\n    src = inspect.getsource(simple)', '    from prooflens.status import LABELS\n    src = "\\n".join(label for label, _ in LABELS.values())'))

def paper_tests(s):
    for const, colour, code in [('NOT_CHECKED', 'declared', 'link.no-audit'), ('NOT_IN_AUDIT', 'declared', 'link.not-in-audit'), ('NOT_LINKED', 'unspecified', 'link.none')]:
        s = s.replace('{"status": ' + const + ', "class": "' + colour + '"}', '{"status": ' + const + ', "class": "' + colour + '", "status_code": "' + code + '"}')
    return s
edit('tests/simple/test_paper.py', paper_tests)
p = root / 'engine/python/prooflens/data/schema/manifest-claim.schema.json'
d = json.loads(p.read_text()); d['properties']['status_code'] = {'type': 'string', 'description': 'Result code selected from evidence; status is display text, never control flow.'}; p.write_text(json.dumps(d, indent=2) + '\n')

sys.path.insert(0, str(root / 'engine/python'))
from prooflens.status import LABELS
by_label = {label: code for code, (label, _) in LABELS.items()}
# One-time fixture regeneration, not a runtime compatibility parser.
def walk(x):
    changed = False
    if isinstance(x, dict):
        if 'status' in x and x['status'] in by_label:
            x['status_code'] = by_label[x['status']]; changed = True
        for v in x.values():
            changed = walk(v) or changed
    elif isinstance(x, list):
        for v in x:
            changed = walk(v) or changed
    return changed
for p in (root / 'web/tests/fixtures').rglob('*.json'):
    d = json.loads(p.read_text())
    if walk(d):
        p.write_text(json.dumps(d, ensure_ascii=False, separators=(',', ':')) + '\n')
