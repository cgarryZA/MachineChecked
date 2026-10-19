"""Read a complete, revision-bound public audit as data for a canonical paper page."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Lock
import hashlib
import json
import re
from urllib.parse import quote, urlsplit, urljoin

from . import manifest as mf
from . import versions
from .status import fields, STATUSES
from .util import content_id
from .schemas import validate
from jsonschema import ValidationError


class AuditError(ValueError):
    """A registered audit is unavailable or incompatible with this reader."""


def relative_url(base: str, path: str) -> str:
    """Resolve an audit file inside its HTTPS directory."""
    if not isinstance(path, str) or not re.fullmatch(r"[A-Za-z0-9_./-]+", path):
        raise AuditError("Invalid audit file path")
    if path.startswith('/') or any(p in ('', '.', '..') for p in path.split('/')):
        raise AuditError("Audit file path leaves its directory")
    return urljoin(base, path)


def audit_version(desc: dict) -> str:
    """Publication identity, including a rebuild at the same project commit."""
    return content_id({k: desc.get(k) for k in ('schema', 'release', 'formalisation', 'papers', 'data')})


def paper_version(value) -> dict | None:
    """The paper version an audit's descriptor says it pins, rebuilt from its kind and
    identifier: the label shown is the one MachineChecked gives that version, never a label the
    audit supplies (a manuscript is never shown with a version number). `checked` is true only
    when the audit says every claim's pin was checked against the version; an audit that does
    not say so is read as unchecked."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise AuditError('Invalid paper version')
    kind, vid, rev = value.get('kind'), value.get('id'), value.get('revision')
    checked = value.get('checked') is True
    if kind == 'manuscript':
        if not isinstance(rev, str) or not versions.COMMIT.fullmatch(rev) or \
                vid != 'manuscript:' + rev[:versions.SHORT]:
            raise AuditError('Invalid manuscript version')
        return {**versions.manuscript_record(rev), 'checked': checked}
    if kind == 'published' and isinstance(vid, str) and vid:
        rec = versions.published_version(('arXiv:' + vid[6:]) if vid.startswith('arxiv:') else vid)
        if rec['id'] != vid:
            raise AuditError('Invalid published version')
        return {**rec, 'revision': rev if isinstance(rev, str) else None, 'checked': checked}
    raise AuditError('Invalid paper version')


def same_version(a: str, b: str) -> bool:
    """Whether two version identifiers name one version (a manuscript's commit may be given
    abbreviated)."""
    if a.startswith('manuscript:') and b.startswith('manuscript:'):
        return versions.same_commit(a[11:], b[11:])
    return a.lower() == b.lower()


def load_published_audit(paper: dict, project: dict, listing: dict, fetch) -> dict:
    """Fetch and validate one snapshot. ``fetch(url, byte_limit)`` returns bytes.

    The public paper identity and version must match the listing. PDF coordinates remain
    attached to the audit's verified PDF bytes. The original paper PDF keeps its own anchors.
    All claim chunks and their declaration closure are required; partial snapshots are refused.
    """
    base = listing['url'].rstrip('/') + '/'
    u = urlsplit(base)
    if u.scheme != 'https' or not u.hostname or u.query or u.fragment or u.username or u.password:
        raise AuditError('Use an HTTPS audit directory')

    downloaded = 0
    lock = Lock()
    def read_bytes(path, limit):
        nonlocal downloaded
        raw = fetch(relative_url(base, path), limit)
        with lock:
            downloaded += len(raw)
            if len(raw) > limit or downloaded > 512_000_000:
                raise AuditError("Audit exceeds the download limit")
        return raw

    def read(path, limit=10_000_000):
        value = json.loads(read_bytes(path, limit))
        if not isinstance(value, dict):
            raise AuditError("Audit data must be a JSON object")
        return value

    def contract(obj, name):
        try:
            validate(obj, name)
        except ValidationError as e:
            raise AuditError(f"Invalid {name} data at " + "/".join(map(str, e.absolute_path))) from e

    d = read('audit.json', 1_000_000)
    if d.get('schema') != 'machinechecked/audit@1':
        raise AuditError('Unsupported audit descriptor; rebuild the audit')
    f = d.get('formalisation') or {}
    if f.get('repository', '').lower() != project['repository'].lower():
        raise AuditError('Audit repository differs from the listed project')
    if not re.fullmatch(r'[0-9a-f]{40}', f.get('commit') or ''):
        raise AuditError('Audit needs a full project commit')
    matches = [p for p in d.get('papers', []) if
               (p.get('id') == paper['id'] or
                (paper['id'].startswith('curated:') and p.get('url') in
                 [v for v in paper.get('links', {}).values() if v]))]
    if len(matches) != 1:
        raise AuditError('Audit needs one matching public paper identifier')
    public = matches[0]
    expected_version = project.get('paper_version')
    if expected_version and public.get('version') != expected_version:
        raise AuditError('Audit paper version differs from the listing')
    pinned = paper_version(public.get('paper_version'))
    # A listing that names the version it lists this audit under (`version`, an identifier as
    # `paper_version.id` gives it) needs an audit that pins that version.
    if listing.get('version') and not (pinned and same_version(listing['version'], pinned['id'])):
        raise AuditError('Audit pins another version of the paper than the listing names')
    raw_index = read(d['data'], 20_000_000)
    idx = deepcopy(raw_index)
    if idx.get('schema') != mf.SCHEMA:
        raise AuditError('Audit uses older reader data; rebuild with the current MachineChecked version')
    if idx.get('release') != d.get('release') or not d.get('release'):
        raise AuditError('Audit descriptor and data name different releases')
    if idx.get('project', {}).get('commit') != f['commit'] or idx.get('project', {}).get('repository', '').lower() != f['repository'].lower():
        raise AuditError('Audit descriptor and data name different project revisions')
    # Validate shape after normalising unknown codes, never using labels as logic.
    for row in idx.get('claims', []):
        code = row.get('status_code')
        row.update(fields(code if code in STATUSES else 'unknown'))
    contract(idx, 'manifest-index')
    ps = idx.get('papers', [])
    matched = [p for p in ps if p.get('id') == public.get('key')] if public.get('key') else ps if len(ps) == 1 else []
    if len(matched) != 1:
        raise AuditError('Audit needs an unambiguous internal paper key')
    ap = matched[0]
    revision = ap.get('revision') or ap.get('source_commit')
    if paper_version(ap.get('paper_version')) != pinned:
        raise AuditError('Audit descriptor and data name different paper versions')
    if not revision or revision != public.get('revision'):
        raise AuditError('Audit paper revisions disagree')
    rows = [c for c in idx.get('claims', []) if c.get('paper') == ap['id']]
    if len(rows) > 5000 or len({c['id'] for c in rows}) != len(rows):
        raise AuditError('Audit claim inventory is too large or has duplicate identifiers')

    def claim(row):
        rec = read('data/claims/' + row['file'])
        expected_code = rec.get('status_code') if rec.get('status_code') in STATUSES else 'unknown'
        if expected_code != row.get('status_code') or any(rec.get(k) != row.get(k) for k in ('id', 'paper')) or rec.get('release') != idx['release'] or rec.get('schema') != mf.SCHEMA:
            raise AuditError('Audit claim chunk disagrees with its index')
        code = rec.get('status_code')
        # Unknown codes stay unknown, independently of the supplied display label/class.
        rec = {**rec, **fields(code if code in STATUSES else 'unknown')}
        contract(rec, 'manifest-claim')
        anchor = rec.get('anchor')
        if row.get('anchor') != mf.index_anchor(anchor, (anchor or {}).get('kind', 'unlocated')):
            raise AuditError('Audit claim locations disagree with the index')
        return {**row, **fields(rec['status_code']), 'record': rec,
                'link': '/read/?audit=' + quote(base, safe='') +
                        '#/r/' + quote(idx['release'], safe='') + '/read/' + quote(ap['id'], safe='') + '/' + quote(rec['id'], safe='')}

    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(claim, rows))
        keys = sorted({k for c in records for k in c['record'].get('decls', {}).values()})
        if len(keys) > 10000:
            raise AuditError('Audit declaration closure is too large')
        def declaration(key):
            if not re.fullmatch(r'[0-9a-f]{24}', key):
                raise AuditError('Invalid declaration key')
            rec = read('data/decls/' + key + '.json')
            if mf.record_key(rec) != key:
                raise AuditError('Audit declaration hash mismatch')
            return key, rec
        store = dict(pool.map(declaration, keys))

        # Definitions expanded at their applications, stored on their own and referred to by
        # key from statements, declarations and other expansions (`mf.split_expansions`).
        def expansion(key):
            if not re.fullmatch(r'[0-9a-f]{24}', key):
                raise AuditError('Invalid expansion key')
            rec = read('data/expansions/' + key + '.json', 2_000_000)
            if mf.record_key(rec) != key:
                raise AuditError('Audit expansion hash mismatch')
            return key, rec
        expansions = {}
        wanted = set().union(*(mf.expansion_keys(c['record']) for c in records),
                             *(mf.expansion_keys(r) for r in store.values()))
        while wanted:
            if len(expansions) + len(wanted) > 100_000:
                raise AuditError('Audit has too many expansions')
            got = dict(pool.map(expansion, sorted(wanted)))
            expansions.update(got)
            wanted = set().union(*(mf.expansion_keys(r) for r in got.values())) - set(expansions)
    pdfs = {}
    edition = None
    if ap.get('pdf'):
        raw = read_bytes('data/' + ap['pdf'], 100_000_000)
        digest = hashlib.sha256(raw).hexdigest()
        if not raw.startswith(b'%PDF') or digest != ap.get('pdf_sha256'):
            raise AuditError('Audit PDF hash mismatch')
        edition = 'audit-' + digest
        pdfs[edition] = raw
    audited_paper = {**ap, 'pdf': f'papers/{edition}.pdf' if edition else None,
                     'pdf_url': None, 'edition': edition, 'revision': revision}
    # A changing publication must be retried as a whole on the next build.
    if read('audit.json', 1_000_000) != d or read(d['data'], 20_000_000) != raw_index:
        raise AuditError('Audit changed during download; retry the build')
    return {'author': d.get('author') or listing.get('author'), 'url': base,
            'commit': f['commit'], 'release': idx['release'], 'version': audit_version(d),
            'paper_version': pinned,
            'claims': records, 'store': store, 'expansions': expansions, 'pdfs': pdfs, 'paper': audited_paper,
            'context': {k: idx.get(k) for k in ('release', 'evidence', 'project', 'lean', 'issues', 'site_url', 'created', 'tool')},
            'gates': idx.get('gates', {}).get(ap['id']), 'state': 'loaded'}
