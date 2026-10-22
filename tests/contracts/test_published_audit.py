import copy
import json
import pytest
from published_fixture import BASE, PAPER, REPO, files, snapshot, build
from prooflens.paper import apply_audits, write_paper_site
from prooflens.published import AuditError, audit_version


def test_full_evidence_and_project_revision_survive_import(tmp_path):
    index, audit = build(tmp_path)
    row = index['claims'][0]
    c = json.loads((tmp_path/'data/claims'/row['file']).read_text())
    rec = c['by_project'][REPO]['record']
    assert rec == audit['claims'][0]['record']
    assert rec['clauses'][0]['evidence'] == {
        'formal': {'state':'proved'}, 'review': {'state':'author-reviewed'},
        'source': {'state':'fail','placement':'exact'}, 'replay': {'state':'not-run'}}
    assert c['by_project'][REPO]['audit']['context']['project']['commit'] == 'a'*40
    assert c['by_project']['synthetic/beta']['status_code'] == 'link.none'
    assert 'record' not in c['by_project']['synthetic/beta']
    assert len(index['claims']) == 2
    assert index['claims'][1]['projects'] == [REPO]
    for k in rec['decls'].values(): assert (tmp_path/'data/decls'/f'{k}.json').is_file()
    # The expansions the statement refers to, and those they refer to, come with the audit and
    # are written on the paper page under their keys.
    assert len(audit['expansions']) == 2
    for k, x in audit['expansions'].items():
        assert json.loads((tmp_path/'data/expansions'/f'{k}.json').read_text()) == x


def test_exact_locations_stay_with_the_pdf_they_describe(tmp_path):
    index,audit = build(tmp_path)
    row=index['claims'][0]
    assert row['anchor']['kind'] == 'approximate'
    assert row['by_project'][REPO]['anchor']['y0'] == 220
    assert row['by_project'][REPO]['audit']['audit_anchor']['kind'] == 'exact'
    edition=index['editions'][0]
    assert (tmp_path/'data'/edition['pdf']).read_bytes() == next(iter(audit['pdfs'].values()))
    claims=[{'key':'x','kind':'theorem','number':'Theorem 1','links':[], 'anchor':None}]
    apply_audits(claims,{REPO:audit},audit['paper']['pdf_sha256'])
    same=write_paper_site(tmp_path/'same',PAPER,claims,None,None,audits={REPO:audit})
    assert same['claims'][0]['by_project'][REPO]['anchor']['kind'] == 'exact'


@pytest.mark.parametrize('part,key,value',[
 ('audit.json','schema','machinechecked/audit@99'),
 ('data/index.json','schema','prooflens/manifest@0'),
 ('data/index.json','release','r-other'),
])
def test_incompatible_contract_is_rejected(part,key,value):
    d=files();d[part][key]=value
    with pytest.raises(AuditError): snapshot(d)


@pytest.mark.parametrize('change', ['repository','paper','version','revision','commit','duplicate','pdf','decl','chunk','expansion'])
def test_wrong_or_partial_snapshot_is_rejected(change):
    d=files();desc=d['audit.json']; idx=d['data/index.json']
    if change=='repository':desc['formalisation']['repository']='another/project'
    if change=='paper':desc['papers'][0]['id']='arxiv:2601.99999'
    if change=='version':desc['papers'][0]['version']='v2'
    if change=='revision':desc['papers'][0]['revision']='c'*40
    if change=='commit':idx['project']['commit']='c'*40
    if change=='duplicate':idx['claims'].append(copy.deepcopy(idx['claims'][0]))
    if change=='pdf':d['data/papers/T.pdf']+=b'changed'
    if change=='decl':d[next(k for k in d if k.startswith('data/decls/'))]['value']='False'
    if change=='expansion':d[next(k for k in d if k.startswith('data/expansions/'))]['checked']=False
    if change=='chunk':d['data/claims/'+idx['claims'][0]['file']]['id']='another'
    with pytest.raises(AuditError):snapshot(d)


@pytest.mark.parametrize('path',['../secrets.json','https://elsewhere.example/data.json','/data.json','data/%2e%2e/x','data/\\x'])
def test_audit_file_paths_stay_in_the_publication(path):
    d=files();d['audit.json']['data']=path
    with pytest.raises(AuditError):snapshot(d)


def test_duplicate_numbers_keep_distinct_records_and_mark_ambiguous_join(tmp_path):
    a=snapshot();a['claims'][1]['number']='Theorem 1';a['claims'][1]['record']['number']='Theorem 1'
    cs=[{'key':'one','number':'Theorem 1','kind':'theorem','links':[], 'anchor':None}]
    apply_audits(cs,{REPO:a})
    assert cs[0]['audit'][REPO]['status_code']=='unknown'
    assert len(cs)==3 and len({c['key'] for c in cs})==3


def test_future_code_is_unknown_even_when_prose_says_accepted():
    d=files();row=d['data/index.json']['claims'][0];rec=d['data/claims/'+row['file']]
    for r in [row,rec]:r.update(status_code='future.accepted',status='formal: accepted',**{'class':'accepted'})
    a=snapshot(d)
    assert a['claims'][0]['record']['status_code']=='unknown'
    assert a['claims'][0]['class']=='unspecified'


def test_publication_identity_changes_on_new_release_at_same_commit():
    d=files()['audit.json'];old=audit_version(d);d['release']='new-release'
    assert audit_version(d)!=old


def test_inconsistent_coordinates_are_rejected():
    d=files();d['data/index.json']['claims'][0]['anchor']['y0']=999
    with pytest.raises(AuditError, match='locations'):snapshot(d)


def test_failure_is_visible_without_asserting_an_unpublished_audit(tmp_path):
    cs=[{'key':'x','number':'Theorem 1','kind':'theorem','links':[], 'anchor':None}]
    idx=write_paper_site(tmp_path,PAPER,cs,None,None,audits={REPO:{'state':'unavailable','detail':'offline'}})
    assert idx['claims'][0]['by_project'][REPO]['status_code']=='audit.unavailable'
    assert idx['audits'][REPO]['detail']=='offline'


def test_two_audits_keep_conflicting_results_and_reviews_separate(tmp_path):
    a=snapshot(); b=copy.deepcopy(a)
    b['context']['project']={'repository':'synthetic/beta','commit':'b'*40}
    b['claims'][0].update(status_code='formal.open')
    b['claims'][0]['record'].update(status_code='formal.open')
    b['claims'][0]['record']['clauses'][0]['spec_review']['current']=[]
    cs=[{'key':'x','number':'Theorem 1','kind':'theorem','links':[], 'anchor':None}]
    apply_audits(cs,{REPO:a,'synthetic/beta':b})
    idx=write_paper_site(tmp_path,PAPER,cs,None,None,audits={REPO:a,'synthetic/beta':b})
    c=json.loads((tmp_path/'data/claims'/idx['claims'][0]['file']).read_text())
    assert c['by_project'][REPO]['record']['status_code']=='formal.author-reviewed'
    assert c['by_project']['synthetic/beta']['record']['status_code']=='formal.open'
    assert c['by_project'][REPO]['record']['clauses'][0]['spec_review']['current']
    assert c['by_project']['synthetic/beta']['record']['clauses'][0]['spec_review']['current']==[]


def test_publication_change_during_download_requires_retry():
    from published_fixture import fetcher
    from prooflens.paper import load_published_audit
    d=files(); raw=fetcher(d); times=0
    def changing(url, limit):
        nonlocal times
        if url==BASE+'audit.json':
            times+=1
            if times==2: d['audit.json']['release']='r-next'
        return raw(url,limit)
    with pytest.raises(AuditError,match='changed during'):
        load_published_audit(PAPER,PAPER['formalisations'][0],{'url':BASE},changing)


def test_audits_of_one_version_are_ordered_by_stars_and_never_combined(tmp_path):
    """#212: the most-starred audit is the default, the others follow by stars, and each claim
    keeps every audit's own status; without a count for every audit, the listing's order holds."""
    from published_fixture import BETA, combined
    idx = combined(tmp_path / 'a', stars={REPO: 3, BETA: 7})
    assert (idx['audit_order'], idx['audit_order_by']) == ([BETA, REPO], 'stars')
    assert idx['stars'] == {BETA: 7, REPO: 3}
    rows = {c['number']: c for c in idx['claims']}
    assert rows['Theorem 1']['status_code'] == 'formal.open', 'the default audit gives the summary'
    assert rows['Theorem 1']['by_project'][REPO]['status_code'] == 'formal.author-reviewed'
    assert 'audit' not in rows['Theorem 2']['by_project'][REPO]
    assert rows['Theorem 2']['by_project'][BETA]['audit']['claim'] == 'T:two'
    for stars in (None, {REPO: 3}, {REPO: 3, BETA: -1}, {REPO: 3, BETA: '7'}):
        idx = combined(tmp_path / 'b', stars=stars)
        assert (idx['audit_order'], idx['audit_order_by']) == ([REPO, BETA], 'listing')
        assert 'stars' not in idx or idx['stars'] == {}


def test_audits_of_another_version_are_not_drawn_on():
    from prooflens.paper import audit_order
    v1 = {'state': 'loaded', 'paper_version': {'id': 'arxiv:2601.01234v1'}}
    v2 = {'state': 'loaded', 'paper_version': {'id': 'arxiv:2601.01234v2'}}
    m = {'state': 'loaded', 'paper_version': {'id': 'manuscript:abc1234'}}
    m2 = {'state': 'loaded', 'paper_version': {'id': 'manuscript:abc1234' + '0' * 33}}
    audits = {'a/x': v1, 'b/y': v2, 'c/z': {'state': 'unavailable'}, 'd/w': {'state': 'loaded'}}
    assert audit_order(['a/x', 'b/y', 'c/z', 'd/w'], audits, None) == (['a/x'], 'listing')
    assert audit_order(['a/x', 'b/y'], audits, {'a/x': 1, 'b/y': 2}) == (['b/y'], 'stars')
    assert audit_order(['d/w', 'a/x'], audits, None) == (['d/w'], 'listing')
    assert audit_order(['a/x', 'b/y'], {'a/x': m, 'b/y': m2}, None)[0] == ['a/x', 'b/y']
    assert audit_order(['c/z'], audits, None) == ([], 'listing')


def test_a_version_entry_carries_its_audits_commits():
    from prooflens.paper import page_versions
    entry = {'id': 'arxiv:2601.01234v1', 'kind': 'published', 'href': '/p/v1/',
             'audits': [{'url': BASE, 'author': 'A', 'repository': REPO, 'commit': 'a' * 40},
                        {'url': BASE + 'x/', 'author': 'B', 'commit': 'not a commit'}]}
    out = page_versions([entry], entry['id'])[0]['audits']
    assert out[0]['commit'] == 'a' * 40 and 'commit' not in out[1]
