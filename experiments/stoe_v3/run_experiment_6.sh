#!/usr/bin/env bash
#
# run_experiment_6.sh
# ===================
# Pre-registered runner for experiment 6 (see PREREG.md).
#
# Executes two conditions under identical flags except --seed-path:
#
#   Condition A: native SToE seed     (--seed-path seed/stoe_seed.json)
#   Condition B: chimera (SToE names, music graph)  (--seed-path seed/stoe_chimera_seed.json)
#
# Both conditions: K-topology mode, K mechanism on, ontology surfaced.
# K=50 seeds, max 3 attempts, fresh field per puzzle, 6-puzzle goldilocks subset.
#
# Drop this file into the root of stoe_v3/ (alongside PLAN.md and harness/).
# Run from that directory.
#
# Reproducibility: the chimera seed SHA256 is verified before run B starts.
# If the chimera seed has been rebuilt or tampered with, the runner halts.

set -euo pipefail

cd "$(dirname "$0")"

# --- Pre-flight ---
test -f harness/cli.py             || { echo "harness/cli.py not found; run from stoe_v3/ root"; exit 2; }
test -f seed/stoe_seed.json        || { echo "seed/stoe_seed.json missing"; exit 2; }
test -f seed/stoe_chimera_seed.json || {
    echo "seed/stoe_chimera_seed.json missing — build it first:"
    echo "  python scripts/build_chimera_seed.py \\"
    echo "      --stoe  seed/stoe_seed.json \\"
    echo "      --music seed/music_theory_seed.json \\"
    echo "      --out   seed/stoe_chimera_seed.json"
    exit 2
}

# Verify chimera SHA matches the build-time stamp. Refuse to run otherwise.
if [[ -f seed/.chimera.sha256 ]]; then
    EXPECTED=$(cat seed/.chimera.sha256 | awk '{print $1}')
    ACTUAL=$(sha256sum seed/stoe_chimera_seed.json | awk '{print $1}')
    if [[ "$EXPECTED" != "$ACTUAL" ]]; then
        echo "CHIMERA SHA MISMATCH:"
        echo "  expected: $EXPECTED"
        echo "  actual:   $ACTUAL"
        echo "Refusing to run. Either restore the pre-registered chimera or"
        echo "explicitly re-pre-register with the new seed."
        exit 3
    fi
    echo "Chimera SHA verified: $ACTUAL"
else
    echo "WARNING: seed/.chimera.sha256 not present. Recording current SHA as canonical."
    sha256sum seed/stoe_chimera_seed.json > seed/.chimera.sha256
fi

# --- Locked parameters ---
# These are the §5 pre-registered values. Do NOT edit without bumping PREREG.md.
PUZZLES="LG-003 LG-004 LG-005 LG-006 LG-009 CSP-002"
SEEDS=50
MAX_ATTEMPTS=3
MODEL="${OLLAMA_MODEL:-qwen2.5:32b}"
OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
RUN_DIR="runs"
mkdir -p "$RUN_DIR"
TS=$(date +%Y%m%d_%H%M%S)

# --- Common flags (locked) ---
# --mode topology              : K-topology condition (pre-registered)
# --ontology-manifest          : K mechanism part 1 — manifest in prompt
# --mention-edges              : K mechanism part 2 — observer-mediated edges
# --include-seed-ontology      : let context builder reach the seed (required for fair K test)
# --fresh-field                : no cross-puzzle bleed
COMMON_FLAGS=(
    --mode topology
    --seeds "$SEEDS"
    --max-attempts "$MAX_ATTEMPTS"
    --fresh-field
    --include-seed-ontology
    --ontology-manifest
    --mention-edges
    --model "$MODEL"
    --ollama-url "$OLLAMA_URL"
    --out-dir "$RUN_DIR"
)

run_condition () {
    local label="$1"
    local seed_path="$2"
    echo
    echo "========================================================================"
    echo "Condition $label : --seed-path $seed_path"
    echo "  K=$SEEDS seeds × 6 puzzles = 300 trials, max $MAX_ATTEMPTS attempts each"
    echo "  model=$MODEL"
    echo "========================================================================"
    python -m harness.cli \
        "${COMMON_FLAGS[@]}" \
        --seed-path "$seed_path" \
        --puzzles $PUZZLES
    # The CLI writes runs/<ts>_topology.json by default; rename so the analyzer
    # can find conditions A and B unambiguously.
    LATEST=$(ls -t "$RUN_DIR"/*_topology.json | head -1)
    DEST="$RUN_DIR/exp6_${TS}_${label}_topology.json"
    cp "$LATEST" "$DEST"
    echo "  -> $DEST"
}

# --- Run both conditions ---
START=$(date +%s)
run_condition A seed/stoe_seed.json
run_condition B seed/stoe_chimera_seed.json
END=$(date +%s)
echo
echo "Wall time: $(( (END - START) / 60 )) min"

# --- Analyze ---
A_REPORT=$(ls -t "$RUN_DIR"/exp6_${TS}_A_topology.json | head -1)
B_REPORT=$(ls -t "$RUN_DIR"/exp6_${TS}_B_topology.json | head -1)
python scripts/analyze_experiment_6.py \
    --condition-a "$A_REPORT" \
    --condition-b "$B_REPORT" \
    --out "$RUN_DIR/exp6_${TS}_verdict.json"

echo
echo "Verdict written to $RUN_DIR/exp6_${TS}_verdict.json"
