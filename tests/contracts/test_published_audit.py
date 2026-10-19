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


@pytest.mark.parametrize('change', ['repository','paper','version','revision','commit','duplicate','pdf','decl','chunk'])
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
