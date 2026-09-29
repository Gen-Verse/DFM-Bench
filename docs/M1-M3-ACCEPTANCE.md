> Historical archive (2026-09-27). This describes the earlier pilot, not the portable v1 workflow. Use the root README for current commands and scoring semantics. Referenced private artifacts are intentionally not distributed.

# M1–M3 acceptance handoff

Implemented directly on Phai. No model calls, training, scientific execution, source migrations or GitHub publication were performed.

## Verification

- 33 deterministic tests passed, including tests run against the installed wheel.
- Wheel built without downloading dependencies and installed in the dedicated .venv.
- Two real runs reconciled against independent read-only SQL queries.
- Repeated captures produced identical canonical snapshot IDs.
- Source database and WAL hashes remained unchanged during capture.
- All four complete domain rubrics and all 11 JSON contracts are packaged.

## Reconciled runs

| Domain | Candidates / edges | Recorded / started / closed episodes | Compile ever / current | Ready candidates / attempted |
|---|---|---|---|---|
| clinical | 168 / 142 | 169 / 166 / 165 | 38 / 37 | 7 / 32 |
| battery | 351 / 367 | 200 / 200 / 200 | 60 / 50 | 41 / 60 |

These are historical operational results, not a comparison of scientific quality.
The EHR run is operator-stopped with four unclosed episode records; three of those never started. The battery run has all episodes closed but still retains the operator-stop end reason.
Compilation ever-passed totals include earlier successful attempts whose jobs later changed state; current status alone misses these.

## Evidence coverage

- Clinical: 1,212 supporting-artifact references frozen privately.
- Battery: 922 references frozen privately; one oversized attachment explicitly unavailable under the 1 MiB default.
- References are not counts of unique scientific evidence: many candidates reuse artifacts.
- Readiness package versions are identified for all started readiness attempts. Compilation package-version rates are withheld because failed attempts often have no completed package manifest.
- Raw datasets were not copied. No configuration secrets, native traces or credentials were exported.
- Private proposal/support text is not redacted or approved for public release; M4 reviewer preparation remains pending.

## Locations

- Package/repository: /data_storage/yl_test/zjy/dfm-bench
- Acceptance manifest: /data_storage/yl_test/zjy/dfm-bench-evaluations/20260927-m1-m3-final/acceptance.json
- EHR report: /data_storage/yl_test/zjy/dfm-bench-evaluations/20260927-m1-m3-final/clinical/report.md
- Battery report: /data_storage/yl_test/zjy/dfm-bench-evaluations/20260927-m1-m3-final/battery/report.md

## Human checkpoint

Review one report per domain and confirm the episode/candidate/attempt definitions, stop status, retry interpretation and evidence gaps. M4 will then provide blinded scientific review packets. Scientific quality, valid-package assessment, contribution deduplication, expert calibration and public task release are not implemented in M1–M3.

## Development snapshots

The earlier 20260927-m1-m3 and 20260927-m1-m3-v1 directories are development imports retained for audit. They are superseded by 20260927-m1-m3-final and are not the acceptance release.
