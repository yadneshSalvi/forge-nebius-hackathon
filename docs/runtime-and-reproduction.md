# Runtime and portable reproduction

FORGE's qualified local physics runtime is macOS arm64, Python 3.11, MuJoCo 3.3.7 and NumPy 2.2.6 on CPU. The original three-axis Cartesian gantry uses physical actuator, contact and friction dynamics to pick and release a free cuboid. Its learned component is an instrumented-state NumPy waypoint MLP above a fixed phase controller. This release has no physical robot, Isaac, GR00T or CUDA qualification.

The evidence archive is a self-contained snapshot: `campaign.json`, canonical `objects/{sha}.json`, frozen `engine/` and `control/` source, pinned `requirements.txt`, the reproduction command and `checksums.json`. It does not need the original database, original data directory, application server, browser, provider credentials or NVIDIA model service to replay physics. Model-planning and image-analysis receipts remain historical evidence; the command does not call those models again.

## Prepare the runtime

Extract the archive into a clean directory. Keep the Python environment and any output files outside that directory so the verifier can account for every bundled file.

```sh
python3.11 -m venv /tmp/forge-reproduction-env
/tmp/forge-reproduction-env/bin/python -m pip install -r /absolute/path/to/bundle/requirements.txt
```

Dependency installation may download wheels. Once the pinned environment is installed, verification and replay work offline. An existing local wheelhouse can also be installed with pip's `--no-index --find-links /absolute/path/to/wheels` options. The development environment is roughly 266 MB; it contains no large pretrained model weights. The NumPy policy weights are ordinary bounded JSON artifacts inside the bundle.

## Verify the archive

```sh
/tmp/forge-reproduction-env/bin/python /absolute/path/to/bundle/scripts/reproduce.py \
  --bundle /absolute/path/to/bundle --verify
```

The command returns a JSON report and checks:

- Every declared file checksum and the exact file set, rejecting missing/unlisted files, symlinks, absolute paths and path traversal.
- Canonical JSON and SHA-256 filenames for every content-addressed object, plus complete artifact references.
- The scientific source hash against the campaign configuration and source-lock snapshot. File names are read from the bundled lock declaration without importing server or provider code.
- The frozen task, checkpoint schema/tensors/normalization, demonstration source bindings, exact successful expert-oracle components, and episode evidence hashes.
- Complete training demonstration lineage and ordered training-manifest hashes, including all base demonstrations referenced through `base_index_sha` in either the campaign root or configuration.
- Dense-trace geometry and contact-oracle reconstruction where dense traces exist, including individual protected-object contact-point forces. Bulk episodes with compact traces retain their original per-step oracle aggregates and receive integrity checks; a compact trace does not permit a full independent trajectory reconstruction.

Checksum verification establishes consistency within the supplied snapshot. It is not an external signature or independent proof that every scientific claim is true. The readable task, source, raw geometry, contacts and learning lineage are supplied for that review.

## Rerun a recorded failure

```sh
/tmp/forge-reproduction-env/bin/python /absolute/path/to/bundle/scripts/reproduce.py \
  --bundle /absolute/path/to/bundle --rerun-sample
```

This always verifies the archive first. It loads `campaign.config.base_checkpoint_sha`, selects the first completed failure of that frozen base checkpoint, preferring a fully recorded episode, and runs fresh local MuJoCo physics from the stored scenario and registered nuisance seed. It does not reuse the recorded poses as actions or select a revised policy that makes the scene pass.

The JSON compares actual success, terminal reason, every oracle component, the policy observations/actions and all terminal metrics. Discrete values must match exactly. Floating-point metrics use absolute tolerance `1e-6` and relative tolerance `1e-7`; the report lists each mismatch. The command compares pinned MuJoCo and NumPy versions and Python major/minor version before running. It also reports whether OS and architecture match the recorded host. Identical outcomes on another platform are not assumed; physics differences remain visible.

## Rerun a corrective demonstration

```sh
/tmp/forge-reproduction-env/bin/python /absolute/path/to/bundle/scripts/reproduce.py \
  --bundle /absolute/path/to/bundle --rerun-demo
```

This selects the first accepted corrective demonstration in the curriculum, verifies its binding to the successful expert episode and reruns the same contact expert. To inspect another demonstration, provide its content-addressed object SHA after `--rerun-demo`. This is successful-demonstration replay, not policy retraining. The base and revised tensors, optimizer budgets, seeds, losses and data lineage remain available in the exported objects for separate training reproduction.

All three options may be combined. Exit status is `0` when verification and requested comparisons pass, `1` when fresh physics differs from recorded evidence, or `2` for malformed/incompatible evidence or a runtime error. JSON output goes to stdout; commands do not create a data store or write into the archive.

## Evidence conventions

World coordinates are SI, right-handed and z-up. Quaternions use WXYZ; free-joint angular velocities in raw qvel are body-local, while replay frame angular velocities are world coordinates. Box dimensions are half extents and geometric transforms are body-local. The 25 Hz browser replay samples come from 500 Hz authoritative MuJoCo states. Browser interpolation is presentation only.

An engine episode's content hash excludes measured wall time and its own hash field. A checkpoint's whole content hash includes measured training time, so rerunning deterministic training need not produce byte-identical checkpoint files. Compare actual tensor hashes and policy outputs when checking training determinism. Partial or interrupted attempts have no task verdict and are excluded from failure/success denominators. Replaying an identical nuisance seed establishes repeatability, not a new independent probability estimate.

`tests/test_reproduction.py` exercises the production export path and executes the exported script from an unrelated directory after deleting the original test data. It also checks path and symlink attacks, missing artifacts, source changes, object tampering, rehashed demonstration-label tampering and rehashed dense-oracle inconsistencies. These checks qualify the local reproduction flow, not robot hardware or broad manipulation performance.
