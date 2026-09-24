# Conformance runner

```bash
pip install -r runner/requirements.txt
python runner/run_conformance.py --component certify --output-dir results/certify
python runner/run_conformance.py --combined --parallel --output-dir results/combined
python runner/result_diff.py --previous results/previous.json --current results/combined/results.json
```

Optional official driver (after `./scripts/bootstrap-official-scripts.sh`):

```bash
python runner/run_conformance.py --component verify \
  --official-script runner/vendor/run-test-plan.py
```
