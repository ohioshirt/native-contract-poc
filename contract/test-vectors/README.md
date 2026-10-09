# Exhaustive test vectors

The exhaustive vectors are generated from the active `specification.json`; the machine-readable specification is the only authority. Generate runner input with:

```sh
python3 verification/generate.py --wire-input --output scenarios.json
```

This yields all `E^0 ∪ E^1 ∪ E^2 ∪ E^3 ∪ E^4` sequences in deterministic product order, with IDs `s0000` onward. For the current 5-event alphabet, the expected count is 781. Generate expected output independently with `python3 verification/generate.py --output expected-traces.json`. `scripts/verify.sh` creates both run artifacts in its output directory. Regenerate them after a contract version change; do not add a hand-maintained partial sample to the exhaustive count. A readable named example may be stored separately from the generated exhaustive artifact.
