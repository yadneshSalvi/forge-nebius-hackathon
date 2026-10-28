# Recorded starter

`recorded-sample.tar.xz` is a lossless recording of actual local FORGE evidence. Its adjacent `.sha256` file identifies the exact archive. It contains:

- Completed v2 development campaign `fg-a7f42769f2`, including both measured boundaries, successful demonstrations, all five seeds per arm and actual NVIDIA receipts.
- Registered final campaign `fg-8a43e14455`, its 8,000 paired outcomes, frozen manifest, policies and global exposure registry.
- The separately labeled non-nominated seed-404 reproduction `fg-faf764de0e`, with both full raw traces.
- A summary of v1's negative development result with original source/report/archive digests. The full historical v1 ZIP is retained on the development workstation and is not part of this starter.

The raw scientific objects and hashes are preserved. Stale local PIDs and launch tokens are removed; the primary campaign is marked recorded on import. The full model-call receipts exclude the separate reasoning-content field. No provider credentials are included.

From the repository root, with the pinned Python environment installed:

```sh
.venv/bin/python scripts/import_recorded_sample.py
```

The importer requires an empty data store or an identical prior import. It refuses active work and conflicting metadata, validates paths/checksums/object bindings and restores the final-case exposure registry. It runs no physics, training or network request. To inspect in an isolated data directory, pass `--data /absolute/path/to/new-data` and start the application with `FORGE_DATA_DIR` set to that directory.

The original source and evaluation locks remain binding. This recording is meant for the matching committed implementation; changing scientific files does not turn old evidence into a validation of new code. The runtime's normal JSON/ZIP export contains frozen sources and offline physics reproduction tooling for a complete portable audit.

Checksums establish consistency with the supplied snapshot. They are not a third-party signature or hardware safety certification.

## Incident workbench add-on

`nebius-incident-test.zip` is a separate 2,179,312-byte executable recording of incident `inc-657a996d965c43a3a8f9`. Its SHA-256 is `af6d2ead51ac44bf087569f51fb84a294fa2c85af802620c72ca21cb14d454df`. It preserves 42 actual episodes, the frozen original/checkpoint/reset schedule, complete outcomes, three dense oracle traces, compact fresh-pair traces and the accepted NVIDIA proposal linked to its original metered receipt. The measured 20 fresh paired rescues are a post-final diagnostic, not a replacement policy score. `nebius-incident-test.json` summarizes the exact result.

`incident-planner-receipts.json` additionally retains all four actual intervention-planning calls, the rejected unsupported narrative, both reviews and the single local schema revalidation. The revalidation adds no call or cost. To make the completed diagnostic and provider role visible in a new local app, run this after the starter import:

```sh
.venv/bin/python scripts/import_incident_recording.py
```

It accepts only the included, hash-verified recording and its exact completed parent/source/checkpoint. It refuses active or conflicting work, preserves original campaign rows and does not duplicate costs on repeated import. An actual fresh starter→incident import passed with network and new physics denied, all 500 exposure cases preserved, and byte-identical ZIP re-export; see [the import acceptance record](incident-import-acceptance.json).

The ZIP also runs directly outside the checkout without importing either recording. Extract it and follow its `REPRODUCE.md` for verification, all-pair replay and an alternate compatible checkpoint. See [the incident workbench contract](../docs/incident-workbench.md) and [independent orchestrator acceptance](orchestrator-incident-qa.json).

`groot-local-preflight.json` records a deliberately blocked local GPU check. The [GR00T/LIBERO package](../docs/groot-worker-qualification.md) supplies pinned future launch/capture commands; it contains no downloaded model weights or claimed GR00T rollout.
