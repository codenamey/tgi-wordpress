import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('release_builder', Path(__file__).resolve().parents[1] / 'scripts/builder.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)


class PromotionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.art = Path(self.temp.name)
        self.destination = 'ghcr.io/codenamey/tgi-wordpress'
        self.revision = 'f' * 40
        self.data = b.locked('8.4')
        self.exact = self.destination + ':php8.4.27-wp7.1.3-r3'
        self.manifests = {}
        self.descriptors = []
        self.runtime_refs = {}
        for arch, runtime_char, index_char, attest_char in [('amd64', 'a', 'c', '1'), ('arm64', 'b', 'd', '2')]:
            platform = 'linux/' + arch
            ref = self.destination + '@sha256:' + index_char * 64
            runtime = self.destination + '@sha256:' + runtime_char * 64
            self.runtime_refs[platform] = runtime
            descriptors = [
                {'digest': 'sha256:' + runtime_char * 64, 'platform': {'os': 'linux', 'architecture': arch}},
                {'digest': 'sha256:' + attest_char * 64, 'platform': {'os': 'unknown', 'architecture': 'unknown'},
                 'annotations': {'vnd.docker.reference.type': 'attestation-manifest'}}]
            self.manifests[ref] = {'manifests': descriptors}
            self.descriptors.extend(descriptors)
            self.write(f'candidate-8.4-{arch}.json', {'source_revision': self.revision,
                'platform': platform, 'reference': ref, 'runtime_reference': runtime, 'inputs': self.data,
                'build_revision': b.config()['build_revision'], 'brotli': b.config()['brotli'],
                'extensions': b.config()['extensions'], 'wp_cli': b.config()['wp_cli']})
            self.write(f'verified-8.4-{arch}.json', {'image': runtime, 'architecture': arch})
            self.write(f'integration-8.4-{arch}.json', {'image': runtime, 'passed': True})
            self.write(f'trivy-8.4-{arch}.json', {'ArtifactName': runtime,
                'Metadata': {'OS': {'Family': 'debian', 'Name': '13'}}, 'Results': []})
        self.combined_ref = self.destination + '@sha256:' + 'e' * 64
        self.manifests[self.combined_ref] = {'manifests': self.descriptors}
        self.calls = []
        self.real_run = b.run
        self.addCleanup(patch.stopall)
        patch.object(b, 'ART', self.art).start()
        patch.object(b, 'release_context', return_value=(self.destination, self.data, self.revision, self.exact)).start()
        patch.object(b, 'run', side_effect=self.command).start()

    def write(self, name, value):
        (self.art / name).write_text(json.dumps(value))

    def command(self, *args, **kwargs):
        self.calls.append(args)
        if len(args) > 1 and args[1] == b.ROOT / 'scripts/security_gate.py':
            return self.real_run(*args, **kwargs)
        if args[:5] == ('docker', 'buildx', 'imagetools', 'inspect', '--raw'):
            return json.dumps(self.manifests[args[5]])
        if args[:4] == ('docker', 'buildx', 'imagetools', 'inspect'):
            return json.dumps({'digest': 'sha256:' + 'e' * 64})
        if args[:4] == ('docker', 'buildx', 'imagetools', 'create'):
            return ''
        raise AssertionError(args)

    def assert_not_promoted(self):
        self.assertFalse(any(self.exact in call for call in self.calls))
        self.assertFalse((self.art / 'release-8.4.json').exists())

    def test_promotes_checked_runtime_digests_and_preserves_attestations(self):
        b.promote('8.4')
        release = json.loads((self.art / 'release-8.4.json').read_text())
        self.assertEqual(release['runtime_references'], self.runtime_refs)
        self.assertEqual(release['reference'], self.combined_ref)
        self.assertIn(('docker', 'buildx', 'imagetools', 'create', '-t', self.exact,
            '-t', self.destination + ':8.4', '-t', self.destination + ':8.4-latest', self.combined_ref), self.calls)

    def test_stale_or_incomplete_evidence_never_promotes(self):
        path = self.art / 'candidate-8.4-arm64.json'
        candidate = json.loads(path.read_text())
        candidate['source_revision'] = '0' * 40
        self.write(path.name, candidate)
        with self.assertRaisesRegex(ValueError, 'committed release inputs'):
            b.promote('8.4')
        self.assert_not_promoted()

    def test_new_critical_raw_report_blocks_promotion(self):
        path = self.art / 'trivy-8.4-arm64.json'
        report = json.loads(path.read_text())
        report['Results'] = [{'Class': 'os-pkgs', 'Vulnerabilities': [{'VulnerabilityID': 'CVE-2026-12345',
            'PkgName': 'example', 'InstalledVersion': '1', 'Severity': 'CRITICAL'}]}]
        self.write(path.name, report)
        with self.assertRaises(subprocess.CalledProcessError):
            b.promote('8.4')
        self.assert_not_promoted()

    def test_changed_runtime_digest_never_promotes(self):
        self.manifests[self.combined_ref] = {'manifests': [
            dict(m, digest='sha256:' + '9' * 64) if m['platform']['architecture'] == 'arm64' else m
            for m in self.descriptors]}
        with self.assertRaises(ValueError):
            b.promote('8.4')
        self.assert_not_promoted()

    def test_lost_attestation_never_promotes(self):
        self.manifests[self.combined_ref] = {'manifests': [m for m in self.descriptors
            if m['platform']['os'] == 'linux']}
        with self.assertRaisesRegex(ValueError, 'attestation'):
            b.promote('8.4')
        self.assert_not_promoted()

    def test_native_worker_rejects_wrong_architecture_before_build(self):
        with patch.object(b, 'run', return_value='linux/amd64') as run:
            with self.assertRaisesRegex(ValueError, 'natively'):
                b.publish('8.4', platform='linux/arm64')
        self.assertEqual(len(run.call_args_list), 1)


if __name__ == '__main__':
    unittest.main()
