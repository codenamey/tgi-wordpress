#!/usr/bin/env python3
"""Lightweight systemd PHP update watcher. No Docker, AI or site deployment."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import urllib.request

REPOSITORY = 'codenamey/tgi-wordpress'
PUBLIC_REMOTE = 'https://github.com/' + REPOSITORY + '.git'
PUSH_REMOTE = 'git@github.com:' + REPOSITORY + '.git'


def run(args, cwd=None, env=None):
    result = subprocess.run(args, cwd=cwd, env=env, check=True, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=210)
    return result.stdout.rstrip('\n')


def release_status(sha):
    if not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise ValueError('Invalid pending commit')
    url = 'https://api.github.com/repos/' + REPOSITORY + '/actions/workflows/release.yml/runs?head_sha=' + sha + '&event=push&per_page=5'
    req = urllib.request.Request(url, headers={'User-Agent': 'tgi-wordpress-updater', 'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(req, timeout=30) as response:
        runs = json.load(response)['workflow_runs']
    if not runs:
        return {'status': 'awaiting_workflow', 'commit': sha}
    item = max(runs, key=lambda r: r['id'])
    return {'status': item['status'], 'conclusion': item['conclusion'], 'url': item['html_url'], 'commit': sha}


def tick(state, check=False):
    state = Path(state)
    previous_file = state / 'status.json'
    previous = json.loads(previous_file.read_text()) if previous_file.exists() else {}
    status = {'checked_at_utc': datetime.now(timezone.utc).isoformat(), 'repository': REPOSITORY}
    if previous.get('pending_commit'):
        status['pending_commit'] = previous['pending_commit']
        status['pending_since_utc'] = previous.get('pending_since_utc', status['checked_at_utc'])
        status['release'] = release_status(previous['pending_commit'])
        if status['release']['status'] == 'awaiting_workflow':
            age = datetime.now(timezone.utc) - datetime.fromisoformat(status['pending_since_utc'])
            if age.total_seconds() > 3600:
                status['release']['conclusion'] = 'startup_failure'
                status['action'] = 'workflow_not_started'
                return status
        if status['release']['status'] in ('queued', 'in_progress', 'waiting', 'requested', 'pending', 'awaiting_workflow'):
            status['action'] = 'waiting_for_release'
            return status
    with tempfile.TemporaryDirectory(prefix='check-', dir=state) as scratch:
        checkout = Path(scratch) / 'repo'
        run(['git', 'clone', '--quiet', '--depth', '1', '--branch', 'master', PUBLIC_REMOTE, str(checkout)])
        base = run(['git', 'rev-parse', 'HEAD'], cwd=checkout)
        command = [sys.executable, 'scripts/prepare_update.py', 'prepare']
        if check:
            command.append('--check')
        update = json.loads(run(command, cwd=checkout))
        status['update'] = update
        if not update['changed'] or check:
            status['action'] = 'check_only' if check else 'up_to_date'
            return status
        changes = run(['git', 'status', '--porcelain'], cwd=checkout).splitlines()
        if {line[3:] for line in changes} != {'versions/versions.yaml', 'versions/lock.json'}:
            raise ValueError('Updater changed unexpected files')
        run(['git', 'add', 'versions/versions.yaml', 'versions/lock.json'], cwd=checkout)
        versions = ', '.join(change['to'] for change in update['changes'])
        run(['git', '-c', 'user.name=TGI PHP updater', '-c', 'user.email=tgi-php-updater@users.noreply.github.com',
             'commit', '--quiet', '-m', '[tgi-auto-php-patch] Update PHP ' + versions], cwd=checkout)
        # Use the same transition verifier as the privileged release workflow.
        run([sys.executable, 'scripts/prepare_update.py', 'verify', '--base', base], cwd=checkout)
        sha = run(['git', 'rev-parse', 'HEAD'], cwd=checkout)
        env = dict(os.environ)
        env['GIT_TERMINAL_PROMPT'] = '0'
        env['GIT_SSH_COMMAND'] = shlex.join(['ssh', '-i', str(state / 'deploy_key'), '-o', 'IdentitiesOnly=yes',
            '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + str(state / 'known_hosts')])
        # Non-fast-forward pushes fail safely; the next tick retries from fresh master.
        run(['git', 'push', PUSH_REMOTE, 'HEAD:refs/heads/master'], cwd=checkout, env=env)
        status['action'] = 'published_update_commit'
        status['pending_commit'] = sha
        status['pending_since_utc'] = status['checked_at_utc']
        status['commit_url'] = 'https://github.com/' + REPOSITORY + '/commit/' + sha
        return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', type=Path, default=Path('/var/lib/tgi-wordpress-updater'))
    parser.add_argument('--check', action='store_true', help='Read-only upstream check; no commit or push')
    args = parser.parse_args()
    args.state_dir.mkdir(parents=True, exist_ok=True)
    with (args.state_dir / 'updater.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = tick(args.state_dir, args.check)
        tmp = args.state_dir / 'status.json.tmp'
        tmp.write_text(json.dumps(result, indent=2) + '\n')
        tmp.replace(args.state_dir / 'status.json')
        print(json.dumps(result, sort_keys=True), flush=True)
        return 1 if result.get('release', {}).get('conclusion') in ('failure', 'cancelled', 'timed_out', 'action_required', 'startup_failure') else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as exc:
        # Do not print SSH command environment or credential files.
        print('Updater command failed: ' + str(exc.cmd[:2]) + ': ' + (exc.stderr or '')[-2000:], file=sys.stderr)
        sys.exit(1)
    except (ValueError, KeyError, OSError, subprocess.TimeoutExpired) as exc:
        print('Updater failed: ' + str(exc), file=sys.stderr)
        sys.exit(1)
