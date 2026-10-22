# Scripts

The executable shell wrappers invoke the standard-library Python builder.
Use a working Python 3.9+ on PATH, or set TGI_PYTHON to its absolute path. `resolve.sh` refreshes the source lock;
`build.sh <branch>` consumes it, builds locally, and verifies actual components;
`test.sh <branch>` adds disposable database/HTTP/persistence checks;
`scan.sh <branch>` emits an SBOM and runs Trivy's critical-fixable gate.
`build-all.sh` explicitly reports disabled branches. `check-updates.sh` writes an
observation report without modifying the accepted lock. `publish.sh` requires an approved registry destination and explicit matching
authorization (see docs/versioning.md).

`python3 scripts/builder.py matrix` emits a GitHub Actions include matrix;
`image <branch>` emits the local exact image tag. Any missing/disabled branch,
unsupported architecture or component mismatch fails with a nonzero exit code.
Source downloads are verified by SHA256 and GPG within the Docker build.

`bash scripts/finish-local.sh` performs the bounded local build, integration and
scanner checks for both currently required branches, retaining evidence in
artifacts/local-results.json. It uses a digest-pinned Trivy container when a
host Trivy installation is unavailable. It never logs into a registry or pushes.

Security scans keep an unfiltered raw report and pass it through security_gate.py
with security/reviews.json. Reviewed findings remain in the evidence; new
critical findings, fixed-version availability, scope changes and expiry fail
closed. Redis source and exact extension version are verified during build.
