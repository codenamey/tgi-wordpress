#!/usr/bin/env bash
# Bounded local verification: no registry login, push, deployment, or Git mutations.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ "$(uname -s)" == Darwin ]]; then
  PYTHON=/usr/bin/python3
else
  PYTHON=python3
fi
export PYTHONPYCACHEPREFIX="$ROOT/artifacts/pycache"
mkdir -p artifacts
if [[ "${1:-}" == prepare-redis ]]; then
  curl --fail --location --retry 3 --retry-all-errors --max-time 120 \
    https://codeload.github.com/phpredis/phpredis/tar.gz/df4fab2de7fc327c54c94a13af2b9542e4fbd720 \
    --output artifacts/redis-source.tar.gz
  "$PYTHON" - <<'PY'
import hashlib
import tarfile
from pathlib import Path
p=Path('artifacts/redis-source.tar.gz')
assert p.stat().st_size > 0
print('SHA256:',hashlib.sha256(p.read_bytes()).hexdigest())
with tarfile.open(p) as tar:
    prefix='phpredis-df4fab2de7fc327c54c94a13af2b9542e4fbd720/'
    Path('docker/redis-LICENSE').write_bytes(tar.extractfile(prefix+'LICENSE').read())
    for line in tar.extractfile(prefix+'php_redis.h').read().decode().splitlines():
        if 'PHP_REDIS_VERSION' in line: print(line)
PY
  exit 0
fi
if [[ "${1:-}" == docker-status ]]; then
  "$PYTHON" - <<'PY'
import subprocess
for cmd in [['docker', 'version'], ['docker', 'desktop', 'status']]:
    try:
        result = subprocess.run(cmd, timeout=15, text=True, capture_output=True)
        print(result.stdout, result.stderr)
    except subprocess.TimeoutExpired:
        print('Timed out:', ' '.join(cmd))
PY
  exit 0
fi
if [[ "${1:-}" == inspect-release ]]; then
  for branch in 8.4 8.5; do
    image_ref="$("$PYTHON" scripts/builder.py image "$branch")"
    echo "$image_ref"
    docker run --rm "$image_ref" php -m
    docker run --rm "$image_ref" php -r 'echo json_encode(["php"=>PHP_VERSION,"mysqli_client"=>mysqli_get_client_info(),"pdo_drivers"=>PDO::getAvailableDrivers()], JSON_PRETTY_PRINT),PHP_EOL;'
    docker run --rm --entrypoint sh "$image_ref" -c 'dpkg-query -W -f="\${Package} \${Version}\n" linux-libc-dev libxml2; if dpkg-query -W -f="\${Status}\n" "linux-image-*" "nfs-kernel-server" 2>/dev/null | grep -q "install ok installed"; then echo "Kernel/NFS package present"; exit 1; else echo "No installed kernel image or NFS server package"; fi'
  done
  exit 0
fi
if [[ "${1:-}" == prepare-imagick ]]; then
  curl --fail --location --retry 3 --retry-all-errors --max-time 120 \
    https://codeload.github.com/Imagick/imagick/tar.gz/70087bab33eab913e99ac77d64d04d1a2fd0b7b0 \
    --output artifacts/imagick-source.tar.gz
  test -s artifacts/imagick-source.tar.gz
  "$PYTHON" - <<'PY'
import hashlib
from pathlib import Path
print(hashlib.sha256(Path('artifacts/imagick-source.tar.gz').read_bytes()).hexdigest())
PY
  exit 0
fi
"$PYTHON" -m unittest discover -s tests -v > artifacts/unit-tests.log 2>&1
"$PYTHON" -m py_compile scripts/builder.py tests/integration.py
SCANNER='aquasec/trivy:0.76.1@sha256:790fd66d1697395d8693d1acaa1ea702406a20f109b6fc7bac8db623eca6c06c'
for branch in 8.4 8.5; do
  echo "Building PHP $branch"
  "$PYTHON" scripts/builder.py build "$branch" > "artifacts/build-$branch.log" 2>&1
  echo "Integration testing PHP $branch"
  "$PYTHON" scripts/builder.py test "$branch" > "artifacts/test-$branch.log" 2>&1
  image_ref="$("$PYTHON" scripts/builder.py image "$branch")"
  echo "Scanning $image_ref"
  docker run --rm -v /var/run/docker.sock:/var/run/docker.sock:ro \
    -v tgi-wordpress-trivy-cache:/root/.cache "$SCANNER" image \
    --image-src docker --ignorefile /dev/null --ignore-unfixed=false \
    --scanners vuln --severity UNKNOWN,LOW,MEDIUM,HIGH,CRITICAL --format json "$image_ref" \
    > "artifacts/trivy-$branch.json" 2> "artifacts/scan-$branch.log"
  docker run --rm -v /var/run/docker.sock:/var/run/docker.sock:ro \
    -v tgi-wordpress-trivy-cache:/root/.cache "$SCANNER" image \
    --image-src docker --format cyclonedx "$image_ref" \
    > "artifacts/sbom-$branch.json" 2> "artifacts/sbom-$branch.log"
  "$PYTHON" scripts/security_gate.py "artifacts/trivy-$branch.json" \
    --reviews security/reviews.json --output "artifacts/security-$branch.json"
  echo "Completed PHP $branch"
done
"$PYTHON" - <<'PY'
import collections
import json
from pathlib import Path
summary = {}
for branch in ['8.4', '8.5']:
    evidence = json.loads(Path(f'artifacts/verified-{branch}.json').read_text())
    integration = json.loads(Path(f'artifacts/integration-{branch}.json').read_text())
    assert evidence['image_id'] == integration['image_id']
    report = json.loads(Path(f'artifacts/trivy-{branch}.json').read_text())
    gate = json.loads(Path(f'artifacts/security-{branch}.json').read_text())
    findings = [v for r in report.get('Results', []) for v in r.get('Vulnerabilities', [])]
    critical = [{k: v.get(k, '') for k in ['VulnerabilityID', 'PkgName', 'InstalledVersion', 'FixedVersion']} for v in findings if v['Severity'] == 'CRITICAL']
    summary[branch] = {'image': evidence['image'], 'image_id': evidence['image_id'],
        'php': evidence['php'], 'wordpress': evidence['wordpress'], 'redis': evidence['redis'], 'architecture': evidence['architecture'],
        'integration_passed': integration['passed'], 'severity_counts': dict(collections.Counter(v['Severity'] for v in findings)),
        'critical_findings': critical, 'actionable_critical': [v for v in critical if v['FixedVersion']],
        'security_passed': gate['passed'], 'reviewed_critical': gate['reviewed_critical'], 'release_authorized': False}
Path('artifacts/local-results.json').write_text(json.dumps(summary, indent=2) + '\n')
print(json.dumps(summary, indent=2))
if any(not e['security_passed'] for e in summary.values()):
    raise SystemExit('Unreviewed critical findings block release; see artifacts/local-results.json')
PY
