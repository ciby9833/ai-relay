#!/usr/bin/env python3
"""Check staged Git blobs (and optionally HEAD history), never print secret values."""
import argparse
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])


def forbidden(path):
    p = pathlib.PurePosixPath(path)
    return (
        any(part in {'secrets', 'credentials', 'backups', 'data', 'uploads',
                     '.git', '.venv', 'node_modules', '__pycache__'} for part in p.parts)
        or (p.name.startswith('.env') and p.name != '.env.example')
        or p.suffix.lower() in {'.pem', '.key', '.p12', '.pfx', '.jks', '.sql',
                                '.dump', '.db', '.sqlite', '.sqlite3', '.log'}
        or p.name.endswith('.sql.gz')
        or (p.suffix == '.json' and (len(p.parts) == 1 or
            any(word in p.name.lower() for word in ('credentials', 'service-account'))))
        or path in {'docs/FEISHU_ACCEPTANCE_LOG.md', 'backend/probe.py'}
    )


def local_secrets():
    values = set()
    env = ROOT / '.env'
    if env.exists():
        for line in env.read_text().splitlines():
            if '=' not in line or line.lstrip().startswith('#'):
                continue
            key, value = line.split('=', 1)
            value = re.split(r'\s+#', value, maxsplit=1)[0].strip().strip('\"\x27')
            if re.search(r'SECRET|PASSWORD|TOKEN|API_KEY|ENCRYPT_KEY', key, re.I) and len(value) >= 8:
                values.add(value)
    # Also reject copies of local service-account fields in source/docs.
    for path in ROOT.glob('*.json'):
        try:
            doc = json.loads(path.read_text())
        except (ValueError, OSError):
            continue
        if isinstance(doc, dict) and doc.get('type') == 'service_account':
            for key in ('private_key', 'private_key_id', 'client_email'):
                if doc.get(key):
                    values.add(doc[key])
    return values


PATTERNS = [
    re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----'),
    re.compile(r'AIza[0-9A-Za-z_-]{30,}'),
    re.compile(r'(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{20,}'),
    re.compile(r'sk-[A-Za-z0-9_-]{20,}'),
    re.compile(r'AKIA[0-9A-Z]{16}'),
    re.compile(r'"type"\s*:\s*"service_account"'),
    re.compile(r'https?://[^\s/:@]+:[^\s/@]+@'),
]


def inspect(path, mode, data, secrets):
    reasons = []
    if forbidden(path):
        reasons.append('private/local file')
    if mode in {'120000', '160000'}:
        reasons.append('symlink or submodule is not allowed')
    content = data.decode('utf-8', errors='replace')
    if any(secret in content for secret in secrets):
        reasons.append('matches a local credential')
    if any(pattern.search(content) for pattern in PATTERNS):
        reasons.append('credential pattern')
    return reasons


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history', action='store_true', help='also scan every commit reachable from HEAD')
    args = parser.parse_args()
    if pathlib.Path(git('rev-parse', '--show-toplevel').decode().strip()).resolve() != ROOT:
        sys.exit('Refusing to scan a parent repository.')
    secrets = local_secrets()
    entries = set()
    for record in git('ls-files', '--stage', '-z').split(b'\0'):
        if record:
            meta, path = record.split(b'\t', 1)
            mode, oid, stage = meta.decode().split()
            if stage != '0':
                sys.exit('Resolve Git conflicts before publishing.')
            entries.add((path.decode(), mode, oid))
    if args.history:
        commits = git('rev-list', 'HEAD').decode().splitlines()
        for commit in commits:
            for record in git('ls-tree', '-rz', commit).split(b'\0'):
                if record:
                    meta, path = record.split(b'\t', 1)
                    mode, kind, oid = meta.decode().split()
                    entries.add((path.decode(), mode, oid))
    failed = False
    for path, mode, oid in sorted(entries):
        data = b'' if mode == '160000' else git('cat-file', 'blob', oid)
        reasons = inspect(path, mode, data, secrets)
        if reasons:
            failed = True
            print(f'BLOCKED {path}: {", ".join(reasons)}', file=sys.stderr)
    if failed:
        return 1
    print(f'Release check passed: {len(entries)} unique file versions; no credential matches found.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
