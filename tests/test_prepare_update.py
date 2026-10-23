import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

scripts = Path(__file__).resolve().parents[1] / 'scripts'
spec = importlib.util.spec_from_file_location('update_builder', scripts / 'builder.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
spec = importlib.util.spec_from_file_location('prepare_update', scripts / 'prepare_update.py')
u = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {'builder': b}):
    spec.loader.exec_module(u)


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.cfg, self.lock = b.config(), b.read(b.LOCK)
        self.new_cfg, self.new_lock = copy.deepcopy(self.cfg), copy.deepcopy(self.lock)
        self.new_cfg['build_revision'] += 1
        self.new_lock['php']['8.4']['version'] = '8.4.99'
        self.new_lock['php']['8.4']['source_sha256'] = 'a' * 64

    def transition(self):
        return u.transition(self.cfg, self.lock, self.new_cfg, self.new_lock)

    def test_patch_increase_and_one_revision_increment(self):
        result = self.transition()
        self.assertEqual(result, [{'branch': '8.4', 'from': self.lock['php']['8.4']['version'], 'to': '8.4.99'}])

    def test_downgrade_new_branch_and_unreviewed_recipe_rejected(self):
        original = copy.deepcopy(self.new_lock)
        for key, value in [('version', '8.4.26'), ('version', '8.5.99'),
                           ('gpg_keys', 'A' * 40), ('source_commit', 'b' * 40),
                           ('source_sha256', self.lock['php']['8.4']['source_sha256'])]:
            self.new_lock = copy.deepcopy(original)
            self.new_lock['php']['8.4'][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.transition()

    def test_security_policy_wordpress_or_php_branch_changes_rejected(self):
        original = copy.deepcopy(self.new_cfg)
        for mutate in [lambda c: c['php']['9.2'].update(enabled=True),
                       lambda c: c['php']['8.4'].update(minimum_version='8.4.0'),
                       lambda c: c['brotli'].update(version='1.1.2')]:
            self.new_cfg = copy.deepcopy(original)
            mutate(self.new_cfg)
            with self.assertRaises(ValueError):
                self.transition()
        self.new_cfg = original
        self.new_lock['wordpress'] = '999.0'
        with self.assertRaises(ValueError):
            self.transition()

    def test_no_change_and_debian_only_drift_do_not_write(self):
        candidate = copy.deepcopy(self.lock)
        for entry in candidate['php'].values():
            entry['base'] = 'debian:trixie-slim@sha256:' + 'b' * 64
        with patch.object(b, 'resolve', return_value=candidate), patch.object(b, 'save') as save:
            self.assertFalse(u.prepare()['changed'])
        save.assert_not_called()

    def test_check_only_does_not_write(self):
        with patch.object(b, 'resolve', return_value=self.new_lock), patch.object(b, 'save') as save:
            result = u.prepare(check=True)
        self.assertTrue(result['changed'])
        save.assert_not_called()

    def test_prepare_validates_everything_before_writing(self):
        self.new_lock['php']['8.5']['gpg_keys'] = 'A' * 40
        with patch.object(b, 'resolve', return_value=self.new_lock), patch.object(b, 'save') as save:
            with self.assertRaises(ValueError):
                u.prepare()
        save.assert_not_called()

    def test_prepare_preserves_other_branches_and_updates_both_files(self):
        candidate = copy.deepcopy(self.new_lock)
        candidate['php']['8.5']['base'] = 'debian:trixie-slim@sha256:' + 'b' * 64
        with patch.object(b, 'resolve', return_value=candidate), patch.object(b, 'save') as save:
            u.prepare()
        self.assertEqual(save.call_args_list[0].args, (b.LOCK, self.new_lock))
        self.assertEqual(save.call_args_list[1].args, (b.CONFIG, self.new_cfg))

    def test_automatic_commit_verifier_rejects_extra_files(self):
        with patch.object(u.subprocess, 'check_output', return_value='versions/lock.json\nversions/versions.yaml\ndocker/Dockerfile\n'):
            with self.assertRaisesRegex(ValueError, 'unexpected changed paths'):
                u.verify('a' * 40)

    def test_verifies_a_real_committed_patch_transition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            versions = root / 'versions'
            versions.mkdir()
            def git(*args):
                return subprocess.check_output(['git', '-C', directory, '-c', 'user.name=Updater test',
                    '-c', 'user.email=updater-test@example.invalid', *args], text=True).strip()
            git('init', '-q')
            for name, value in [('versions.yaml', self.cfg), ('lock.json', self.lock)]:
                (versions / name).write_text(json.dumps(value))
            git('add', 'versions')
            git('commit', '-q', '-m', 'Baseline')
            base = git('rev-parse', 'HEAD')
            for name, value in [('versions.yaml', self.new_cfg), ('lock.json', self.new_lock)]:
                (versions / name).write_text(json.dumps(value))
            git('add', 'versions')
            git('commit', '-q', '-m', '[tgi-auto-php-patch] Test patch')
            with patch.object(b, 'ROOT', root), patch.object(b, 'CONFIG', versions / 'versions.yaml'), patch.object(b, 'LOCK', versions / 'lock.json'):
                self.assertEqual(u.verify(base)['changes'][0]['to'], '8.4.99')


spec = importlib.util.spec_from_file_location('watch_updates', scripts / 'watch_updates.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


class WatcherTests(unittest.TestCase):
    def test_check_and_unchanged_tick_never_push(self):
        for check, changed in [(False, False), (True, True)]:
            with self.subTest(check=check), tempfile.TemporaryDirectory() as state:
                def command(args, **kwargs):
                    if args[:2] == ['git', 'clone']:
                        Path(args[-1]).mkdir()
                        return ''
                    if args[:2] == ['git', 'rev-parse']:
                        return 'a' * 40
                    if 'scripts/prepare_update.py' in args:
                        return json.dumps({'changed': changed, 'changes': []})
                    raise AssertionError('Unexpected mutating operation: ' + repr(args))
                with patch.object(w, 'run', side_effect=command):
                    result = w.tick(state, check=check)
                self.assertIn(result['action'], ['up_to_date', 'check_only'])

    def test_waits_for_existing_release_before_starting_another(self):
        with tempfile.TemporaryDirectory() as state:
            Path(state, 'status.json').write_text(json.dumps({'pending_commit': 'a' * 40}))
            with patch.object(w, 'release_status', return_value={'status': 'in_progress'}), patch.object(w, 'run') as run:
                self.assertEqual(w.tick(state)['action'], 'waiting_for_release')
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
