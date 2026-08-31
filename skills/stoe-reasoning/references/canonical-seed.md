# Canonical SToE seed

The bundled [../assets/stoe_seed.json](../assets/stoe_seed.json) is copied byte-for-byte from the latest validated SToE v9.1 engine source used to build this skill.

Frozen identity:

- SHA-256: `b327db6dbce9981ed21561b9d1a857e2e3786f1391d41edc0381fead79e59868`
- Core IPs: 36
- Typed relations: 113
- Categories: 6 (`Catalyst`, `Fertilizer`, `Hidden Diamond`, `Mirror`, `Seed`, `Star`)
- Non-empty expressions: 36
- Non-empty descriptions: 32

## Loading rules

Load the seed into the persistent reasoning field only when the task actually uses the canonical SToE domain. Preserve every node, edge, category, expression, description, and identifier. Do not silently normalize, paraphrase, or repair its ontology.

Seed and runtime nodes must be eligible for traversal in both directions where typed bridges justify it. Do not make every seed node prompt-visible and do not award an origin bonus merely because a node belongs to SToE.

## Fold/unfold invariant

The entire seed may be folded into a container IP named `SToE_Seed_IP` for storage or navigation bookkeeping. Folding must not destroy internal structure.

```text
fold(seed) → Stoe_Seed_IP
unfold(SToE_Seed_IP) → original canonical nodes and relations
```

After unfolding, verify the frozen hash or a canonical structural digest plus exact counts if the storage representation necessarily changes byte layout. All 36 IPs, 113 typed relations, six categories, expressions, descriptions, and stable identities must reconstruct losslessly.

## Retrieval rule

Only seed nodes reached through the bounded navigator and selected under the same top-k/context budget as runtime IPs may enter active model context. Unreachable seed nodes remain stored but invisible.

Run `python scripts/validate_seed.py` before relying on the bundled seed.
