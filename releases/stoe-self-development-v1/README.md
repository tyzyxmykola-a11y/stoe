# SToE Self-Development Evidence v1

This directory catalogs the stable pre-Hermes-v2.2 evidence boundary for the
public SToE repository.

- Release/tag: stoe-self-development-v1
- Author: Mykola Voronin
- Preparation base: 3ba7d7cafd59bad58c85a02c158c75e07bae3a38
- Scope: observer-aware persistent memory, bounded supervised agent
  self-development, protected evaluation and rollback, conserved failures,
  reproducible experiments, and SToE-Hermes A/B succession

The annotated Git tag is the authoritative identifier for the final release
commit. The preparation-base SHA records the canonical main state from which
the licensing, citation, and catalog files were added; a file cannot embed the
hash of the Git commit that contains that same file without circularity.

## Verified deterministic suites

All suites were rerun from the clean release-preparation worktree:

| Suite | Result |
| --- | ---: |
| Agent | 77/77 |
| SToE-Hermes | 18/18 |
| v9.1 | 50/50 |
| v3 | 21/21 |
| SToE Memory | 9/9 |

No suite required a paid API, cloud model, credential, or running Ollama daemon.

## Evidence represented

Positive evidence includes functioning persistent typed memory, bounded
observer-aware retrieval, protected evaluation and rollback infrastructure,
fresh-process continuity, and reproducible deterministic suites. Experimental
claims remain limited to their frozen benchmarks and documented conditions.

Preserved negative evidence is part of the release. In the latest Hermes v2.1
attempt, the candidate was rejected before execution or activation because the
current validator rejects forbidden syntax inherited unchanged from the trusted
parent. Active Hermes remained unchanged. Earlier malformed outputs, rejected
candidates, null comparisons, and adverse results remain conserved.

This release does not demonstrate AGI, unrestricted recursive self-improvement,
autonomous model-weight modification, production readiness, or proof of the
full SToE ontology. It is not independent scientific confirmation.

## Reproduce and verify

The machine-readable [manifest](manifest.json) records commands, counts,
canonical identities, and artifact hashes. [SHA256SUMS](SHA256SUMS) provides the
same stable artifact set in deterministic path order.

Licensing is mixed and path-specific. Read the repository
[licensing boundary](../../LICENSING.md) and [citation metadata](../../CITATION.cff)
before reuse.
