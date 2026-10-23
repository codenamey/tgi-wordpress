#!/usr/bin/env python3
"""Prepare or verify a bounded PHP patch update. No AI, deployment or publishing."""
import argparse
import copy
import json
import re
import subprocess
import sys

import builder as b


def transition(old_cfg, old_lock, new_cfg, new_lock):
    expected_cfg = copy.deepcopy(old_cfg)
    expected_cfg['build_revision'] += 1
    if new_cfg != expected_cfg or type(new_cfg['build_revision']) is not int:
        raise ValueError('Automatic updates may only increment build_revision by one')
    branches = {branch for branch, item in old_cfg['php'].items() if item['enabled']}
    if set(old_lock['php']) != branches or set(new_lock['php']) != branches:
        raise ValueError('Automatic update cannot add or remove PHP branches')
    if {k: v for k, v in new_lock.items() if k != 'php'} != {k: v for k, v in old_lock.items() if k != 'php'}:
        raise ValueError('WordPress and lock provenance must remain unchanged')
    changes = []
    for branch in sorted(branches):
        before, after = old_lock['php'][branch], new_lock['php'][branch]
        b.locked(branch, cfg=old_cfg, lock=old_lock)
        b.locked(branch, cfg=new_cfg, lock=new_lock)
        # Signing identity, packaging recipe and platforms require human review.
        mutable = {'version', 'source_sha256', 'base'}
        if {k: v for k, v in before.items() if k not in mutable} != {k: v for k, v in after.items() if k not in mutable}:
            raise ValueError('Signing keys, recipe or platform drift: ' + branch)
        previous = tuple(map(int, before['version'].split('.')))
        current = tuple(map(int, after['version'].split('.')))
        if current < previous:
            raise ValueError('PHP downgrade refused: ' + branch)
        if current == previous:
            if after != before:
                raise ValueError('Unchanged PHP branch must retain its accepted lock: ' + branch)
        else:
            if not old_cfg['php'][branch].get('build_from_source'):
                raise ValueError('Automatic patches require source builds')
            if after['source_sha256'] == before['source_sha256']:
                raise ValueError('New PHP release reused the old source checksum')
            changes.append({'branch': branch, 'from': before['version'], 'to': after['version']})
    if not changes:
        raise ValueError('No PHP patch increase; automatic release refused')
    return changes


def prepare(check=False):
    old_cfg, old_lock = b.config(), b.read(b.LOCK)
    candidate = b.resolve(persist=False)
    new_cfg, new_lock = copy.deepcopy(old_cfg), copy.deepcopy(old_lock)
    if set(candidate) != set(old_lock) or {k: v for k, v in candidate.items() if k != 'php'} != {k: v for k, v in old_lock.items() if k != 'php'}:
        raise ValueError('Unexpected lock schema or provenance')
    if set(candidate['php']) != set(old_lock['php']):
        raise ValueError('Unexpected candidate branches')
    changed = False
    for branch, before in old_lock['php'].items():
        after = candidate['php'][branch]
        b.locked(branch, cfg=old_cfg, lock=candidate)
        for key in ['platforms', 'source_commit', 'gpg_keys']:
            if before.get(key) != after.get(key):
                raise ValueError('Manual review required for ' + key)
        if before['version'] == after['version']:
            if before.get('source_sha256') != after.get('source_sha256'):
                raise ValueError('Source checksum changed for an existing PHP release')
            continue  # Debian-only drift must not cause a new PHP release.
        new_lock['php'][branch] = after
        changed = True
    if not changed:
        return {'changed': False, 'changes': []}
    new_cfg['build_revision'] += 1
    changes = transition(old_cfg, old_lock, new_cfg, new_lock)
    if not check:
        try:
            b.save(b.LOCK, new_lock)
            b.save(b.CONFIG, new_cfg)
        except OSError:
            b.save(b.LOCK, old_lock)
            b.save(b.CONFIG, old_cfg)
            raise
    return {'changed': True, 'changes': changes, 'build_revision': new_cfg['build_revision'], 'check_only': check}


def verify(base):
    if not re.fullmatch(r'[0-9a-f]{40}', base):
        raise ValueError('Expected exact base commit SHA')
    def git(*args):
        return subprocess.check_output(['git', '-C', str(b.ROOT), *args], text=True).strip()
    paths = set(git('diff', '--name-only', base, 'HEAD').splitlines())
    if paths != {'versions/lock.json', 'versions/versions.yaml'}:
        raise ValueError('Automatic release contains unexpected changed paths')
    old_cfg = json.loads(git('show', base + ':versions/versions.yaml'))
    old_lock = json.loads(git('show', base + ':versions/lock.json'))
    return {'changed': True, 'changes': transition(old_cfg, old_lock, b.config(), b.read(b.LOCK))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'verify'])
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--base')
    args = parser.parse_args()
    result = prepare(args.check) if args.command == 'prepare' else verify(args.base or '')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError) as exc:
        print('PHP update refused: ' + str(exc), file=sys.stderr)
        sys.exit(1)
