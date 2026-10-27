# Dependency maintenance, 2026-10-27

This review covers the blockers observed on S3 redirect candidate
`4a1748159934060f9f12c5e7bb4728a4a543ece6`, based on main
`98867d1982079a5ea8ab7b8fe11fdcedfafeca5b`. It does not accept the retained Go
risks, authorize public deployment, or change the Go toolchain/RocketMQ client.

## Preserved failures and narrowly reviewed changes

- Main run `40305495179` rejected new npm findings. Its evidence artifact is
  `12643040322` (SHA-256 `38ce4e1545b576c1f4020bae07dbc4fc40485ef3ec19f6e46b13d4eaa4cb58e2`).
- PR run `40440237566`, checkout `93389db3bb5527b77cd0543135a05d245e7b9ea4`,
  rejected the changed Go advisory fingerprint. Artifact `12705653670` has
  SHA-256 `ebd93daab062ff201c49576b0e039ce9698deb32baa5052af0e2210e3d86837d`.
- The Windows and Linux `GO-2026-6809` traces change only the source position of
  `(*S3Client).Delete` calling `io.Copy`: line 123/offset 3465 becomes line
  131/offset 3725 after the constructor change adds eight lines. Module
  inventories, advisory text, symbols and other trace frames are unchanged.
  Both finding fingerprints are updated to this reviewed trace. All three Go
  advisories retain `UNRESOLVED`, their owners/actions, and `risk_accepted=false`.
- The npm lock updates only undici 7.30.0 to 7.30.1, its tarball URL and integrity.
  jsdom 29.1.1 already permits this version. Package count remains 129. The current
  observation binds the new lock hash and npm inventory; no matcher is weakened.

The prior observation/review remain available at the base commit. CI artifacts
are supplementary and may expire; this document records their original IDs and
digests without asserting permanent GitHub artifact availability.

## undici boundary and verification

The upstream [7.30.1 release](https://github.com/nodejs/undici/releases/tag/v7.30.1)
addresses GHSA-f72v-6w45-q472, GHSA-4qv8-2p9j-2685 and GHSA-xjj6-f33q-929c.
The package is a jsdom development dependency. Repository tests load jsdom, but
the application uses browser fetch and its API unit tests stub fetch. No product
exploit path through the affected EventSource/fetch operations is established.

A bounded, synthetic loopback fixture compares the same 14 assertions against
the official 7.30.0/7.30.1 packages and the installed candidate. Four legitimate
SRI/event controls pass in both versions. The old package fails the ten rejection
assertions; 7.30.1 and the installed candidate pass all 14. These cover integrity
token handling, bounded event parser state, and excessive content encodings with
early socket closure in an isolated child process. This is dependency-boundary
evidence, not proof of an exploitable application endpoint.

The first fixture attempt had an incorrect event assertion and insufficient
parser-item inputs. Its failures are retained separately and excluded from the
corrected comparison. Frontend unit tests and production build pass; a fresh
complete lockfile audit reports no npm findings. The Go scan remains three
distinct unresolved advisories, observed independently on Windows and Linux.

The existing dependency-gate negative controls continue to apply. Final PR CI
must validate the committed candidate before merge; local observations are not
main qualification or a release.
