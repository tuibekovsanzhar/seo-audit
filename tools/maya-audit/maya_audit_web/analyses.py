"""Read-only registry for separately processed saved evidence, outside audit history.

No HTTP import, crawl or provider execution. Entries are prepared offline and content-address checked.
"""
import hashlib
import json
import re
from pathlib import Path


class Registry:
    def __init__(self, folder=None):
        self.folder = Path(folder).resolve() if folder else None
        # report path -> ((mtime_ns, size), sha256): every request asks for its audit, and hashing a report of several
        # megabytes on each one is the slow part (D-10). A rewritten file changes its stamp and is hashed again.
        self._digests = {}

    def _digest(self, report):
        stat = report.stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
        cached = self._digests.get(report)
        if cached and cached[0] == stamp:
            return cached[1]
        digest = hashlib.sha256(report.read_bytes()).hexdigest()
        self._digests[report] = (stamp, digest)
        return digest

    @staticmethod
    def accepts(identity):
        return bool(re.fullmatch(r'analysis-[a-z0-9][a-z0-9-]{0,63}', identity))

    def artifacts(self, identity):
        if not self.folder or not self.accepts(identity):
            raise ValueError('Unknown revised analysis')
        path = (self.folder / identity / 'artifacts').resolve()
        if not path.is_relative_to(self.folder) or path == self.folder:
            raise ValueError('Invalid revised analysis path')
        return path

    def get(self, identity):
        if not self.folder or not self.accepts(identity):
            return None
        try:
            folder = self.artifacts(identity)
            manifest = folder.parent / 'analysis.json'
            report = folder / 'report.json'
            if not manifest.resolve().is_relative_to(self.folder) or not report.resolve().is_relative_to(folder):
                return None
            record = json.loads(manifest.read_text(encoding='utf-8'))  # not the Windows code page (D-10, C71)
            meta, audit = record['analysis'], record['audit']
            if not all(isinstance(meta.get(k), str) and meta[k] for k in ('id','label','processed_at','analysis_version','source_audit_id','report_sha256')):
                return None
            if not re.fullmatch(r'[a-f0-9]{32}', meta['source_audit_id']):
                return None
            if meta['id'] != identity or audit['id'] != identity or audit['state'] != 'finished':
                return None
            if self._digest(report) != meta['report_sha256']:
                return None
            return {**audit, 'analysis': meta}
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def list(self):
        if not self.folder or not self.folder.is_dir():
            return []
        rows = [self.get(p.name) for p in self.folder.iterdir() if p.is_dir()]
        return sorted((r for r in rows if r), key=lambda r:r['analysis']['processed_at'], reverse=True)
