"""Synthetic publication with proof, review, source and replay results that deliberately differ."""
import copy
import hashlib
import json
from pathlib import Path

from prooflens import manifest as mf
from prooflens.status import fields
from prooflens.paper import load_published_audit, apply_audits, write_paper_site

BASE = 'https://audit.example/'
REPO = 'synthetic/alpha'
PAPER = {'id': 'arxiv:2601.01234', 'title': 'A synthetic paper', 'authors': ['A. Author'],
         'links': {}, 'formalisations': [
             {'repository': REPO, 'commit': 'b' * 40, 'paper_version': 'v1',
              'audits': [{'url': BASE, 'author': 'A. Author'}]},
             {'repository': 'synthetic/beta', 'commit': 'c' * 40}]}


def files():
    pdf = (Path(__file__).parents[1] / 'web/tests/fixtures/toy/data/papers/T.pdf').read_bytes()
    ap = {'id': 'T', 'title': PAPER['title'], 'mode': 'latex', 'revision': 'd' * 40,
          'pdf': 'papers/T.pdf', 'pdf_sha256': hashlib.sha256(pdf).hexdigest(), 'page_size': [595.28, 841.89]}
    desc = {'schema': 'machinechecked/audit@1', 'author': 'A. Author', 'release': 'r-synthetic',
            'formalisation': {'repository': REPO, 'commit': 'a' * 40}, 'data': 'data/index.json',
            'papers': [{'key': 'T', 'id': PAPER['id'], 'version': 'v1', 'revision': ap['revision']}]}
    decl = {'name': 'Synthetic.bound', 'kind': 'def', 'module': 'Synthetic', 'signature': 'Synthetic.bound : Prop',
            'value': 'True', 'review': {'state': 'author-reviewed', 'current': [{'by': 'Author', 'provenance': 'author', 'text': 'Synthetic definition review.'}]}}
    key = mf.record_key(decl)
    anchor = {'kind': 'exact', 'begin': [1, 0, 110], 'end': [1, 0, 150]}
    claim = {'schema': mf.SCHEMA, 'release': desc['release'], 'id': 'T:one', 'paper': 'T', 'number': 'Theorem 1',
             'kind': 'theorem', 'scope': 'formal', 'scope_reviewed': True, 'scope_note': '',
             **fields('formal.author-reviewed'), 'anchor': anchor, 'statement_tex': 'A synthetic bound.',
             'source_matches': False, 'source_evidence': {'state': 'fail', 'placement': 'exact'},
             'blockers': ['Source changed'], 'findings': [], 'decls': {decl['name']: key},
             'clauses': [{'name': 'original', 'state': 'proved', 'spec': decl['name'],
                          'defs': [decl['name']], 'accept': 'Synthetic.proof',
                          'statement': {'binders': [], 'conclusion': 'True'},
                          'evidence': {'formal': {'state': 'proved'}, 'review': {'state': 'author-reviewed'},
                                       'source': {'state': 'fail', 'placement': 'exact'}, 'replay': {'state': 'not-run'}},
                          'spec_review': {'current': [{'by': 'Author', 'provenance': 'author', 'text': 'Synthetic statement review.'}]}}]}
    extra = copy.deepcopy(claim); extra.update(id='T:prose', number='Paragraph 2', anchor=None)
    extra.update(fields('formal.refuted.corrected'))
    extra['clauses'][0].update(state='refuted', accept=None, refute='Synthetic.refutation')
    extra['clauses'][0]['evidence']['formal']['state']='refuted'
    extra['clauses'].append({'name': 'corrected', 'corrects': 'original', 'state': 'proved', 'statement': {'binders': [], 'conclusion': 'True'}, 'evidence': copy.deepcopy(claim['clauses'][0]['evidence'])})
    index = {'schema': mf.SCHEMA, 'release': desc['release'], 'evidence': 'e'*64,
             'project': {**desc['formalisation'], 'source_roots': ['Synthetic']},
             'issues': REPO, 'summary': {}, 'classes': {}, 'findings': {}, 'papers': [ap], 'gates': {'T': {'release': {'pass': False}}},
             'claims': [{**{k: c.get(k) for k in ('id','paper','number','scope','kind','status_code','status','class')},
                         'counts': {}, 'anchor': mf.index_anchor(c['anchor'], 'exact'), 'file': mf.claim_file(c['id'])} for c in (claim,extra)]}
    return {'audit.json': desc, 'data/index.json': index, 'data/papers/T.pdf': pdf,
            'data/decls/'+key+'.json': decl, **{'data/claims/'+mf.claim_file(c['id']): c for c in (claim,extra)}}


def with_work(data, cid='T:one'):
    """`data` with an auditor's accepted workspace records for `cid` (published_work.py)."""
    fname = next(c['file'] for c in data['data/index.json']['claims'] if c['id'] == cid)
    cur = {'state': 'current', 'changes': []}
    reading = {'workspace': 'ws-000000000000', 'mode': 'informed',
               'reviewer': {'id': 'human:A-Auditor', 'kind': 'human', 'name': 'A Auditor',
                            'identity': 'self-declared'},
               'requirements': [{'id': 'q1', 'kind': 'requirement', 'claim': cid, 'local_id': 'r1',
                                 'form': 'conclusion', 'text': 'the synthetic bound holds',
                                 'depth': 0, 'created_by': 'human:A-Auditor', 'currency': cur}],
               'fragments': [{'id': 'p1', 'kind': 'fragment', 'claim': cid, 'requirement': 'r1',
                              'role': 'statement', 'origin': 'printed', 'state': 'accepted',
                              'state_by': 'human:A-Auditor', 'created_by': 'human:A-Auditor',
                              'passage': {'claim': cid, 'sha256': None}, 'currency': cur}],
               'alignments': [{'id': 'a1', 'kind': 'alignment', 'claim': cid, 'requirements': ['r1'],
                               'relation': 'corresponds', 'lean': [{'decl': 'Synthetic.bound'}],
                               'created_by': 'human:A-Auditor', 'currency': cur}],
               'findings': [{'id': 'f1', 'kind': 'finding', 'claim': cid, 'coverage': 'partial',
                             'state': 'submitted', 'submitted_at': '2026-01-01T00:00:00Z',
                             'evidence': ['e1'], 'in_force': False,
                             'note': 'A synthetic first reading.', 'created_by': 'human:A-Auditor',
                             'currency': cur},
                            {'id': 'f2', 'kind': 'finding', 'claim': cid, 'coverage': 'full',
                             'basis': 'direct', 'state': 'submitted',
                             'submitted_at': '2026-01-02T00:00:00Z', 'evidence': ['e1'],
                             'in_force': True, 'supersedes': 'f1',
                             'reason': 'A synthetic stronger theorem.',
                             'note': 'A synthetic direct reading.', 'created_by': 'human:A-Auditor',
                             'currency': cur}],
               'evidence': [{'id': 'e1', 'kind': 'evidence', 'claim': cid, 'role': 'supports',
                             'ref': {'decl': 'Synthetic.bound'}, 'currency': cur},
                            {'id': 'e2', 'kind': 'evidence', 'claim': cid, 'role': 'supports',
                             'ref': {'certificate': {'theorem': 'Synthetic.no_bound',
                                                     'target': 'Synthetic.Bound',
                                                     'certifies': 'refutes',
                                                     'result': 'checked', 'reasons': []}},
                             'currency': {'state': 'unchecked', 'changes': []}}],
               'counterexamples': [{'id': 'x1', 'kind': 'counterexample', 'claim': cid,
                                    'requirement': 'r1', 'evidence': ['e2'],
                                    'created_by': 'human:A-Auditor', 'currency': cur,
                                    'reading_text': 'the synthetic bound holds',
                                    'analysis': {'form': 'instance', 'decisive': True,
                                                 'standing': 'candidate',
                                                 'standing_text': 'a candidate counterexample: '
                                                                  'not yet shown admissible',
                                                 'shows': 'n = 0 reduces the reading to 1 ≤ 0, '
                                                          'which fails (1 > 0).',
                                                 'problems': []}}]}
    data = copy.deepcopy(data)
    data['data/work/' + fname] = {'schema': 'prooflens/published-work@1',
                                  'release': data['data/index.json']['release'], 'claim': cid,
                                  'readings': [reading]}
    data['data/claims/' + fname]['work'] = 'work/' + fname
    return data


def fetcher(data):
    def fetch(url, limit):
        value = data[url.removeprefix(BASE)]
        return value if isinstance(value, bytes) else json.dumps(value).encode()
    return fetch


def snapshot(data=None):
    return load_published_audit(PAPER, PAPER['formalisations'][0], {'url': BASE}, fetcher(data or files()))


def build(path, reader=None, work=False):
    audit = snapshot(with_work(files()) if work else None)
    claims = [{'key': 'theorem-1', 'number': 'Theorem 1', 'kind': 'theorem', 'links': [],
               'anchor': {'begin': [1,0,220], 'end': [1,0,260]}}]
    apply_audits(claims, {REPO:audit}, 'f'*64)
    index = write_paper_site(path, PAPER, claims, [595.28,841.89], None, reader, {REPO:audit})
    return index, audit


if __name__ == '__main__':
    import sys
    build(Path(sys.argv[1]), Path(sys.argv[2]), work=True)
