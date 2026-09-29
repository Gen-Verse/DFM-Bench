# Portable release 0.2.0

Prepared 2026-09-30 from the Phai Labs evaluator working tree. The source checkout had no committed revision; file hashes before packaging are recorded in SOURCE-PROVENANCE.json. No historical run output, private review packet or source database is included.

Changes:

- Added `dfm-bench-evaluate prepare/review/report` for arbitrary snapshots and output directories. Removed dependency on historical pilot runs, prior opportunity maps, stored credentials and author-specific working directories from this supported workflow.
- Bundled the exact 2026-09-28 v1 protocol and AI-role interpretation rules. Preserved original clinical/battery rubric bytes and registry hashes. The portable plan explicitly replaces historical population, family and applicability choices; it is not a claim to reproduce historical numeric scores.
- Made the existing bounded reviewer accept an explicit model, endpoint and pricing while retaining its historical defaults for existing tests. The portable config requires operator-supplied current rates. No paid test calls were made.
- Added frozen preparation/configuration, content-hash approval, interruption handling, cached resume, partial reports and coverage. All seven path/campaign dimensions are fixed applicable; missing evidence stays unknown. Genuine root-based applicability exclusions require a separately versioned protocol, not score-dependent exclusions.
- Fixed attachment containment checks for trusted-root aliases such as macOS `/var` -> `/private/var`, while continuing to reject symlinks inside the run and files outside it.
- Excluded historical ad-hoc scripts and disabled their module entry points to prevent accidental access to existing private pilot directories. Kept reusable, tested modules.
- Added synthetic end-to-end tests, a no-API smoke example and Linux CI. Python standard-library runtime; Python 3.11+.

Evaluation is read-only with respect to the source run. No source database migrations, GPU jobs, rollouts or training are part of this release. Review packets require local inspection before external judging; automatic scans are not full de-identification. Formal expert calibration and publication claims still require the established human workflow.
