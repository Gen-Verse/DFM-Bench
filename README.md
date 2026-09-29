# DFM-Bench

Evaluate an existing EHR hypothesis-agent run without modifying or restarting the agent. Clone this repository into **any directory**, install it in its own environment, and point it at your run’s `state.sqlite`. No dependency on the original author's checkout, historical pilot outputs, or machine-specific credentials.

The benchmark reports five separate scientific levels: **Hypothesis, Transition, Trajectory, Campaign, Discovery**. It also reports completion, compilation and readiness separately. This is an **internal AI-reviewed preview**; human calibration is pending, and the scores do not establish scientific truth or verified discoveries.

## 1. Clone and install

Requirements: Linux (including the Phai Labs machine) or macOS, Python **3.11+**, Git, and read access to the agent run directory. No GPU, model weights, agent installation, or patient-data download is required. Installation needs access to PyPI for the build tools; the installed evaluator uses the Python standard library only.

```bash
# Run from your own working directory; do not clone over an existing checkout.
git clone https://github.com/JianyuanZhong/dfm-bench.git
cd dfm-bench
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .
dfm-bench --help
dfm-bench-evaluate --help
```

This is a private repository: authenticate with a GitHub account that has repository access, or use your configured GitHub SSH URL. Clone location and source-run location are independent. Once installed, both commands work from any directory while this environment is active.

## 2. Point it at your completed episodes

For a run of approximately 20 episodes, use the run directory containing `state.sqlite`, not the agent project root or an individual compiled task package. The adapter checks the database schema and includes every recorded episode/candidate in that run; it does not assume there are exactly 20 episodes. A row created but never started is reported separately.

```bash
# EDIT these two paths. They are your paths, not the author's historical paths.
RUN_DIR="/absolute/path/to/your/agent/runs/your-run"
EVAL_DIR="/absolute/path/to/your/dfm-results/run-20-episodes"
umask 077
mkdir -p "$EVAL_DIR"

dfm-bench import-run \
  --domain clinical \
  --source "$RUN_DIR/state.sqlite" \
  --output "$EVAL_DIR/snapshot"

dfm-bench verify "$EVAL_DIR/snapshot"
dfm-bench report "$EVAL_DIR/snapshot"
```

**These commands are offline and free.** Read `$EVAL_DIR/snapshot/report.md` to check episode counts, source status, graph structure, artifact availability, compilation and readiness. This operational report **does not score scientific quality**. Continue below for DFM scientific evaluation.

The importer opens SQLite read-only and captures a consistent view including committed WAL data. It never migrates or writes the source database. An existing snapshot directory is rejected; reuse it with `verify`/`report`, or choose a new output directory. Keep evaluation outputs outside the agent run directory. An actively changing run is supported as a point-in-time snapshot, but a completed/quiescent run gives a clearer final assessment; do not stop someone else's run merely to evaluate it.

**Keep the original run files in place.** Registered support files are validated against their recorded paths and hashes. Moving only `state.sqlite` loses attachments. Attachments outside the run, symlinks, oversized files, suspected secrets, and missing/mismatched files are explicitly unavailable; dataset bindings are not copied. The default attachment cap is 1 MiB; raise it explicitly with `--max-artifact-bytes` only if appropriate.

Supported schemas are the EHR thin pairwise schema (`ehr-thin-pairwise-v1`) and its battery counterpart. Required tables: `meta`, `candidates`, `episodes`, `jobs`, `attempts`, `actors`; required columns are defined in [`adapters.py`](src/dfm_bench/adapters.py). Extra columns are tolerated. `Unsupported schema` means a different agent generation needs an adapter; renaming the file or pointing at a different SQLite file will not convert it.

## 3. Prepare the scientific review offline

```bash
dfm-bench-evaluate prepare \
  --snapshot "$EVAL_DIR/snapshot" \
  --output "$EVAL_DIR/review"
```

This freezes the source snapshot identity, v1 protocol, original domain rubrics, interpretation rules, deterministic path selection, and exact review packet hash. It replaces candidate IDs with neutral IDs and removes recognizable private paths/secrets. It makes **no API calls**.

Inspect these local files:

- `review/privacy-audit.json`: coverage and the `packet_hash` you will use below.
- `review/packet.json`: the **exact scientific content** eligible to be sent to the external judge.
- `review/plan.json`: frozen protocol and effective population/scope.

Review packets and snapshots remain private. Heuristic scanning is **not full de-identification**: proposals and registered support attachments may contain sensitive text even when raw dataset bindings and actor traces are excluded. Inspect before sending. If content must change, prepare a separate sanitized source export/snapshot and a new review directory; don't edit a frozen packet in place.

Optionally supply `--opportunity-map /path/to/opportunities.json` to `prepare`. This should describe the starting research opportunities and evidence-backed constraints before seeing scores. An optional `resource_budget` field can record the actual episode/time/token budget and its provenance. Without it, unsupported opportunity/budget dimensions may remain unknown. This is preferable to inventing a campaign score.

## 4. Configure and explicitly run the external judge

The judge is an independent **OpenAI-compatible Chat Completions** service supporting JSON responses, `temperature`, `max_tokens`, billable token usage, and an exact matching returned model ID. The supplied example names the provider/model used in the original pilot; you may choose another suitable external judge. It is not the EHR agent under evaluation.

```bash
# From the cloned repository; outputs and credentials stay outside Git.
cp configs/judge.example.json "$EVAL_DIR/judge.json"
```

Edit `$EVAL_DIR/judge.json`:

| Field | What to enter |
|---|---|
| `model` | Your external judge's exact model ID |
| `endpoint` | Full HTTPS Chat Completions URL, ending in `/chat/completions` |
| `input_usd_per_m` | Current USD per million input tokens |
| `output_usd_per_m` | Current USD per million output tokens |
| `cache_read_usd_per_m` | Current cache-read rate; use the input rate if no verified discount |
| `budget_usd` | Total allowed cost/reservations for this review directory; example: 5 |
| `request_cap` | Maximum HTTP attempts including retries; example: 500 |
| `max_output_tokens` | Output-token ceiling per call; example: 8192 |

**Pricing starts as `null` deliberately:** enter your provider's current rates before review. The evaluator rejects missing/invalid prices before sending anything. The budget is a local estimate/reservation bound using those rates, not a guarantee about a provider invoice. There are at most two attempts per exact request; missing usage retains the reservation.

Store your own API key in a file outside the repository and the review directory, with permission `600`. Do not put a key in the JSON config or command line. For example, create a private file with your editor, then:

```bash
KEY_FILE="$HOME/.config/dfm-bench/judge.key"
chmod 600 "$KEY_FILE"

# After inspecting packet.json, copy its exact hash from privacy-audit.json.
PACKET_HASH="paste-the-64-character-packet_hash-here"

dfm-bench-evaluate review \
  --output "$EVAL_DIR/review" \
  --config "$EVAL_DIR/judge.json" \
  --key-file "$KEY_FILE" \
  --approve-packet-sha256 "$PACKET_HASH"
```

**Only `review` makes paid external calls.** The hash flag records your choice to send that inspected packet. No agent episodes, training, scientific experiments or data production are launched by the evaluator.

The runner reviews all registered hypotheses (seeds separately), every actual parent–child edge, one deterministic longest path per terminal candidate, the full campaign, and a deduplicated contribution ledger per dataset. It is serial and resumable, with cached accepted judgments and a shared cost ledger. Large campaigns require a judge context window that fits the whole campaign; no silent truncation or score-based subsampling occurs. A context rejection stops with preserved partial output.

If interrupted, rerun **the identical `review` command**. Accepted stages are reused. Interrupted requests retain conservative cost reservations. Provider errors, exhausted budgets, and validation failures stop with partial results and exit code 2. Exact requests stop retrying after two attempts; do not delete ledger entries to bypass the budget/retry limits. A different model/configuration/budget or changed evaluator code requires a new review directory (you can reuse the same snapshot).

## 5. Read or rebuild the results

```bash
# Offline; also works before/during an incomplete evaluation.
dfm-bench-evaluate report --output "$EVAL_DIR/review"
```

| File | Contents |
|---|---|
| `review/REPORT.md` | Readable scorecard, coverage and limitations |
| `review/summary.json` | Means, coverage denominators, edge-by-edge ΔH, path/campaign scores, family counts and cost |
| `review/results.json` | Every scientific rating, evidence reference, rationale and contribution family |
| `review/delivery.json` | Separate episode, compilation and readiness statistics |
| `review/plan.json` | Protocol, scope, snapshot identity and implementation fingerprint |
| `review/judge/ledger.json` | Requests, usage, failures and cost/reservations |

All these outputs are private by default. Share an inspected report with your collaborator; do not commit snapshots, request bodies, packets, raw traces, credentials or private task packages.

## Score interpretation

| Level | Measurement |
|---|---|
| Hypothesis | Weighted Q on 1–10: importance 20, novelty 20, grounding 15, falsifiability 10, data resolvability 10, feasibility 10, alternatives 10, actionability 5. Any unknown dimension withholds Q. Generated-candidate mean excludes imported seeds. |
| Transition | Substantive progress / necessary repair / marginal repetition / insufficient evidence. Numerical ΔH is child Q minus parent Q only when both are known. Each crossover parent remains a separate edge. |
| Trajectory | Original L1–L7 rubric, weights 5/30/20/20/10/10/5, 0–4 ratings. Full-scope complete composite is 0–100; missing dimensions withhold it. Single-node paths are unscorable. |
| Campaign | Independent full-DAG T1–T7 rubric, weights 25/15/15/20/10/10/5. A complete score is 0–100, **not an average of node scores**. |
| Discovery | Contribution families grouped by question within each dataset, with maturity, disposition, importance and uncertainty. Proposed families are not confirmed discoveries. |

There is no single total combining the five levels. Completion/readiness is a separate delivery axis. Scores are retrospective judgments of a final snapshot, not evidence available at each historical episode. A maximum score increasing over episodes does not prove learning. Unknowns are not zeros; review completion is not the same as having every composite available.

The portable runner preserves the v1 scoring dimensions and original domain rubric bytes. Its explicit scope differs from historical pilot analysis: all seven trajectory/campaign dimensions remain applicable (missing evidence stays unknown); there is no root-specific applicability adjudication, no historical prefix-ΔT analysis, and families are freshly grouped within one run. The archived protocol includes old population descriptions; the effective scope in `plan.json` supersedes those descriptions for this run. Cross-run discovery comparisons require a joint blinded family adjudication, not subtraction of separately deduplicated family counts.

## Free smoke test after cloning

This creates only a tiny synthetic fixture and makes no model calls:

```bash
SMOKE_DIR="$(mktemp -d)"
python scripts/create_demo_run.py --output "$SMOKE_DIR/run"
dfm-bench import-run --domain clinical --source "$SMOKE_DIR/run" --output "$SMOKE_DIR/snapshot"
dfm-bench verify "$SMOKE_DIR/snapshot"
dfm-bench report "$SMOKE_DIR/snapshot"
dfm-bench-evaluate prepare --snapshot "$SMOKE_DIR/snapshot" --output "$SMOKE_DIR/review"
dfm-bench-evaluate report --output "$SMOKE_DIR/review"
python -m unittest discover -s tests -v
```

The smoke report intentionally says `partial` with no scientific scores because no judge was called. The test suite separately runs all five levels through a deterministic fake judge, checks resume and partial failures, source immutability, budget limits, custom judge configuration, packet integrity, WAL snapshots and missing-evidence behavior. Tests use no real credentials or paid APIs.

## Packaging and provenance

The wheel bundles schemas, clinical/battery rubrics, [`PROTOCOL-V1.json`](src/dfm_bench/protocols/PROTOCOL-V1.json), and [v1 interpretation rules](src/dfm_bench/protocols/interpretation-v1.txt). The archived source hashes are in [`docs/SOURCE-PROVENANCE.json`](docs/SOURCE-PROVENANCE.json). [`docs/RELEASE.md`](docs/RELEASE.md) describes the portable release changes.

Historical `pilot`, `five_level` and `calibration_pilot` modules are retained as tested implementation dependencies and archival code. Their old standalone entry points are disabled in this distribution. Use **`dfm-bench` and `dfm-bench-evaluate`** above for new runs. The separate `calibration-import`, `calibration-report`, and `frontier` commands remain available for advanced workflows; they do not invent human expert labels or turn a frontier into a sixth evaluation level.
