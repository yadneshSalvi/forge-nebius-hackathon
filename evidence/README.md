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
