# Versioning and publishing

`versions/versions.yaml` is the single branch configuration. Enabled branches
form the build matrix. Add a stable future branch only after checking the PHP
recipe, signing keys, extensions and both target architectures. The resolver
never silently downgrades a missing release. Review and commit `versions/lock.json`.

Exact tags: `php<actual-patch>-wp<actual-core>-r<build_revision>`.
Increase build_revision for packaging or Debian changes at the same component
versions. Never overwrite a released exact tag. Branch aliases may move only
after that build is tested, scanned and approved. There is no automatic stable
alias: selecting or moving stable requires explicit approval.

A local build never publishes. publish.sh requires TGI_REGISTRY_DESTINATION and
a matching TGI_PUBLISH_APPROVAL, and refuses a dirty working tree. Before enabling publication, confirm GHCR owner, repository visibility
and full registry destination. The existing Git remote does not by itself approve
a registry destination. Use a protected GitHub release environment and
short-lived GITHUB_TOKEN with packages:write only on the publishing job. Do not
expose secrets to pull_request workflows. Verify the final manifest supports
all configured platforms and record its digest, actual versions, source commits,
SBOM and provenance. Production references should use the recorded digest.

The manual release workflow requires the confirmed registry owner, repository
visibility and explicit publishing authorization. Configure required reviewers
on the `ghcr-release` environment before enabling it. It first runs native CI
for every configured branch/platform, then builds and pushes attested candidates
on native AMD64 and ARM64 runners. Each candidate is verified, integration-tested
and scanned by its runtime digest on the corresponding native runner. A final
job checks source/configuration consistency and re-evaluates the raw scan reports
under the current policy and date, then combines the candidate indexes. It checks
that all runtime and attestation descriptors survive before creating exact and
branch aliases. Failed native workers prevent all promotion jobs.
Each platform is pulled and checked using its own child manifest digest from
the candidate index. This avoids overwriting an index digest in Docker's classic
image store when switching architectures. Promotion retains the complete index,
including SBOM and provenance; release evidence records the checked child references.
Failed candidates remain unpublished as release aliases but can exist in GHCR
under candidate tags; remove them through the registry retention policy.
No stable tag is created. The repository does not create a GitHub remote or
change package visibility. Confirm GHCR package access/visibility separately.

Exact-tag immutability is enforced by a preflight existence check and serialized
workflow runs, not a native GHCR immutability setting. Restrict all other writers
to avoid a race. GitHub Actions have been prepared locally; actual runner and
registry behavior must be validated after setup.
