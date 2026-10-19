<div align="center">

<h1>DFM-Bench</h1>

<p><strong>Evaluating cumulative scientific research progress</strong></p>

<p>
  <a href="https://arxiv.org/abs/2610.23839"><img src="https://img.shields.io/badge/arXiv-2610.23839-B31B1B?logo=arxiv&logoColor=white" alt="DiscoveryRSI on arXiv"/></a>
  <a href="https://github.com/Gen-Verse/DiscoveryRSI"><img src="https://img.shields.io/badge/DiscoveryRSI-GitHub-181717?logo=github&logoColor=white" alt="DiscoveryRSI on GitHub"/></a>
  <a href="https://github.com/Gen-Verse/DFM-Bench/actions/workflows/tests.yml"><img src="https://github.com/Gen-Verse/DFM-Bench/actions/workflows/tests.yml/badge.svg" alt="Deterministic tests"/></a>
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python 3.11 or newer"/>
</p>

</div>

## 🔬 A benchmark for cumulative research progress

**DFM-Bench** evaluates cumulative progress in **life-science research**, with a **battery-science extension**. Introduced as part of [DiscoveryRSI](https://github.com/Gen-Verse/DiscoveryRSI), it evaluates individual hypotheses, revisions against their actual predecessors, ordered development paths, complete research campaigns, and deduplicated scientific contributions.

The benchmark reports **Hypothesis, Transition, Trajectory, Campaign, and Discovery** separately, alongside an independent delivery report for completion, compilation, and readiness. A strong proposal, a productive research process, and a compiled experiment each provide different evidence about research progress.

## 🧭 DFM-Bench at a glance

**1. Five levels of scientific evaluation.** Assess proposal quality, parent–child progress, development paths, whole research graphs, and contribution families. There is no single total combining the five levels; missing evidence remains unknown.

**2. Read-only evaluation of existing runs.** Import a consistent snapshot of a supported agent run without modifying its database or restarting the agent. The portable evaluator runs on Linux and macOS with Python 3.11+ and standard-library runtime dependencies.

**3. Frozen, inspectable reviews.** Preserve the snapshot identity, domain rubrics, protocol, review packet, evidence references, and cost ledger. Prepare and inspect packets offline, then explicitly submit an approved packet to an independent external judge. Reviews support cached resume and partial reports.

## 📦 Resources

| **Type** | **Name** | **Link** |
| --- | --- | --- |
| 📄 Paper | **DiscoveryRSI** | [arXiv:2610.23839](https://arxiv.org/abs/2610.23839) |
| 🧠 Framework | **DiscoveryRSI** | [GitHub](https://github.com/Gen-Verse/DiscoveryRSI) |
| 📖 Guide | **Evaluate your own agent run** | [Evaluation guide](docs/EVALUATION.md) |
| 📐 Protocol | **Frozen v1 scoring protocol** | [Protocol JSON](src/dfm_bench/protocols/PROTOCOL-V1.json) |
| 🧪 Example | **Synthetic agent run** | [Demo fixture](scripts/create_demo_run.py) |

## 🚀 Quick Start

Clone the repository and install the evaluator:

```bash
git clone https://github.com/Gen-Verse/DFM-Bench.git
cd DFM-Bench
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
```

Run the synthetic example. This creates a small fixture, imports a snapshot, and prepares an offline review without credentials, patient data, or model calls:

```bash
SMOKE_DIR="$(mktemp -d)"
python scripts/create_demo_run.py --output "$SMOKE_DIR/run"

dfm-bench import-run \
  --domain clinical \
  --source "$SMOKE_DIR/run" \
  --output "$SMOKE_DIR/snapshot"

dfm-bench verify "$SMOKE_DIR/snapshot"
dfm-bench report "$SMOKE_DIR/snapshot"

dfm-bench-evaluate prepare \
  --snapshot "$SMOKE_DIR/snapshot" \
  --output "$SMOKE_DIR/review"

dfm-bench-evaluate report --output "$SMOKE_DIR/review"
```

Read `$SMOKE_DIR/snapshot/report.md` for the operational report and `$SMOKE_DIR/review/REPORT.md` for review coverage. The review intentionally remains **partial** with no scientific scores until a judge is called.

Run the deterministic test suite:

```bash
python -m unittest discover -s tests -v
```

## 📊 Five Evaluation Levels

| **Level** | **What it evaluates** | **Reported result** |
| --- | --- | --- |
| **Hypothesis** | Importance, novelty, grounding, falsifiability, data resolvability, feasibility, alternatives, and actionability | Weighted quality score on 1–10 when all dimensions are known; imported seeds reported separately |
| **Transition** | Each actual parent–child revision, including each parent of a crossover | Substantive progress, necessary repair, marginal repetition, or insufficient evidence; ΔH when both quality scores are known |
| **Trajectory** | One deterministic longest development path per terminal candidate | Seven-dimension path rubric; complete composite on 0–100, with single-node paths unscorable |
| **Campaign** | The complete research graph and its development process | Independent seven-dimension campaign rubric; complete composite on 0–100 |
| **Discovery** | Contributions grouped by research question within each dataset | Deduplicated families with maturity, disposition, importance, and uncertainty |

Completion, compilation, and readiness are reported on a **separate delivery axis**. Campaign scores are not averages of hypothesis scores, and proposed contribution families are not confirmed discoveries. See the [evaluation guide](docs/EVALUATION.md#score-interpretation) for weights, coverage rules, and scope.

## 🧪 Life Science and Battery Extension

**Life science** is the primary research setting, spanning clinical and population health, therapeutic-target prioritization, disease mechanisms, and population multi-omics. DFM-Bench evaluates how hypotheses in these areas develop through evidence, critique, revision, and synthesis across a research campaign.

The **battery-science extension** applies the same five evaluation levels to battery research, with domain-specific rubrics covering electrochemistry, materials degradation, sensing, and state estimation. The shared evaluation structure supports examining cumulative research progress in both settings, while each domain retains its own scientific criteria.

For installation and evaluation commands, supported run formats, and external-judge setup, see the [complete evaluation guide](docs/EVALUATION.md).

## ⚠️ Limitations and Responsible Use

The bundled v1 protocol remains an **AI-reviewed preview with human calibration pending**. Scores do not establish scientific truth, system superiority, or verified discoveries. They are retrospective assessments of a frozen final snapshot; a rising maximum score over episodes does not by itself prove learning.

Review packets can contain sensitive free text. Automatic scans and neutral IDs are not full de-identification. Inspect packets before external review, keep snapshots and credentials outside Git, and use only data you are authorized to evaluate. The repository includes synthetic fixtures; private runs, patient data, review packets, and credentials are not distributed.

## 📝 Citation

If you use DFM-Bench in your research, please cite the DiscoveryRSI paper:

```bibtex
@article{zhong2026discoveryrsi,
  title={DiscoveryRSI: Recursively Learning to Discover Valuable Hypotheses},
  author={Zhong, Jianyuan and Wu, Chenwei and Yu, Zhaochen and Jiang, Xixian and Li, Xuewei and Xiao, Hao and Dai, Xilin and Wang, Junyang and Zou, Jiaru and Cui, Zhiqing and Zheng, Boyuan and Xiong, Jing and Zhang, Zhen and Gao, Qiang and Morley, Michael and Nakayama, Luis and Xu, Qiang and Shen, Liyue and Gui, Tao and Celi, Leo Anthony and Zou, James and Yin, Zhenfei and Wu, Yingcheng and Yang, Ling},
  journal={arXiv preprint arXiv:2610.23839},
  year={2026}
}
```

## 📚 Documentation and Provenance

The [evaluation guide](docs/EVALUATION.md) contains the full operating procedure. The [release notes](docs/RELEASE.md) describe the portable runner, and [source provenance](docs/SOURCE-PROVENANCE.json) records archived source hashes. Domain rubrics and protocol files retain their original bytes.

Historical pilot documents are retained for context: [five-level protocol archive](docs/FIVE-LEVEL-PROTOCOL.md) and [M1–M3 acceptance archive](docs/M1-M3-ACCEPTANCE.md). Their historical populations and paths do not replace the portable runner's effective scope in `plan.json`.
