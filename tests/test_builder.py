import importlib.util
import unittest
import io
from unittest.mock import patch
from pathlib import Path

spec = importlib.util.spec_from_file_location('builder', Path(__file__).resolve().parents[1] / 'scripts/builder.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)

class ConfigTests(unittest.TestCase):
    def test_disabled_future_branch(self):
        with self.assertRaisesRegex(ValueError, 'disabled'):
            b.selected('9.2')

    def test_unknown_or_injected_branch(self):
        for branch in ['8.3', '8.4;true', None]:
            with self.assertRaises(ValueError): b.selected(branch)

    def test_platforms_fail_closed(self):
        manifest = {'manifests': [{'platform': {'os': 'linux', 'architecture': 'amd64'}}]}
        with self.assertRaisesRegex(ValueError, 'arm64'):
            b.validate_platforms(manifest, ['linux/amd64', 'linux/arm64'])

    def test_attestations_not_runtime_platform(self):
        manifest = {'manifests': [{'platform': {'os': 'unknown', 'architecture': 'unknown'}},
                                  {'platform': {'os': 'linux', 'architecture': 'arm64'}}]}
        self.assertEqual(['linux/arm64'], b.validate_platforms(manifest, ['linux/arm64']))

    def test_lock_matches_config_and_exact_base(self):
        for branch in ['8.4', '8.5']:
            value = b.locked(branch)
            self.assertIn('@sha256:', value['base'])

    def test_vulnerable_php_lock_is_blocked(self):
        lock = b.read(b.LOCK)
        lock['php']['8.4']['version'] = '8.4.26'
        with patch.object(b, 'read', side_effect=lambda path: lock if path == b.LOCK else __import__('json').loads(path.read_text())):
            with self.assertRaisesRegex(ValueError, 'security minimum'):
                b.locked('8.4')

    def test_missing_source_checksum_is_blocked(self):
        lock = b.read(b.LOCK)
        del lock['php']['8.4']['source_sha256']
        with patch.object(b, 'read', side_effect=lambda path: lock if path == b.LOCK else __import__('json').loads(path.read_text())):
            with self.assertRaisesRegex(ValueError, 'source lock'):
                b.locked('8.4')

    def test_resolve_uses_latest_php_net_source_without_binary_image(self):
        cfg = b.config()
        cfg['php'] = {'8.4': cfg['php']['8.4']}
        release = {'version': '8.4.99', 'source': [
            {'filename': 'php-8.4.99.tar.xz', 'sha256': 'a' * 64}]}
        manifest = {'manifests': [
            {'platform': {'os': 'linux', 'architecture': arch}}
            for arch in ['amd64', 'arm64']]}
        with patch.object(b, 'config', return_value=cfg), \
             patch.object(b, 'fetch', return_value=(release, b'')) as fetch, \
             patch.object(b, 'registry_manifest', return_value=(manifest, 'sha256:' + 'b' * 64)) as registry, \
             patch.object(b.urllib.request, 'urlopen', return_value=io.BytesIO(b'ENV GPG_KEYS ' + b'A' * 40)), \
             patch.object(b, 'save') as save:
            lock = b.resolve(persist=False)
        self.assertEqual('8.4.99', lock['php']['8.4']['version'])
        self.assertEqual('a' * 64, lock['php']['8.4']['source_sha256'])
        self.assertIn('www.php.net/releases/', fetch.call_args.args[0])
        registry.assert_called_once_with('debian', 'trixie-slim')
        save.assert_not_called()

if __name__ == '__main__': unittest.main()
