# Submitting for OpenID self-certification

Local Docker runs are a CI gate and a regression detector. Official certification goes
through the OpenID Foundation process against the hosted suite. This page is the bridge
between the two, and it is deliberately explicit about what the local run does **not** prove.

## 1. Confirm the targets

Inji Certify is being tested as an **OpenID4VCI 1.0 issuer** and Inji Verify as an
**OpenID4VP 1.0 verifier** (with the HAIP profile plan). Those are the plan names committed
in `runner/configs/plans.json`:

| Role | Plan |
| --- | --- |
| Inji Certify | `oid4vci-1_0-issuer-test-plan` |
| Inji Verify | `oid4vp-1final-verifier-haip-test-plan` |

Run `--validate-plans` against the suite build you intend to certify with. If a plan or a
variant key is not offered by that build, no amount of green CI means anything.

## 2. Certify against the plan and variant you actually ship

The certification is bound to the combination of plan, variant and configuration that
produced the result. The consumed variant is what is committed in
`runner/configs/issuer-variant.json` and `runner/configs/verifier-variant.json`, and the
rendered plan config is in the same directory. Change one of them and the previous result
no longer describes the product. All three are in the report:

- `results.json` → `plans[].variant`, `plans[].configFile`, `plans[].planName`
- the Extent report → per module: `suite status / result (outcome)` and the plan filename

## 3. Run clean

```bash
./scripts/run-conformance.sh --combined --save-baseline
```

Then make the run defensible before you submit it:

- `runner/configs/expected-failures.json` must be **empty** for a certification candidate.
  A known issue belongs in a waiver with the certifying body, not in a silent skip.
- Review `runner/configs/expected-skips.json` line by line. Every entry is a module that
  did not run. For a submission, each one needs a written justification.
- Check the summary for `handoffSkips` and `unexpectedSkips`: both mean something did not
  run, and both are visible in the report rather than buried.
- `benchmarkMet` must be `true` with `minPassRate: 1.0` over the graded modules.

## 4. Export the evidence

Every run already writes the suite's own exports next to the result:

| Artifact | Path |
| --- | --- |
| Human-readable suite export (HTML) | `results/combined/<component>/*.zip` |
| Signed suite export (JSON) | `results/combined/<component>/*.json.zip` |
| Machine-readable verdicts + evidence | `results/combined/results.json` |
| TestNG results | `testrig-bridge/target/surefire-reports/` |
| Extent Spark report | `testrig-bridge/target/extent/OpenIDConformance-combined.html` |

Keep the signed JSON export: it is the artifact the Foundation can verify, and it is the one
that proves the result came from the suite rather than from this harness.

## 5. Submit

1. Follow [How to Certify Your Implementation](https://openid.net/certification/how-to-certify-your-implementation/).
2. Register the implementation and the plan/variant combination you exercised above.
3. Run the same plan against the hosted certification suite and submit that result.

## What the local run does not prove

- The local stack runs the suite in its `dev` profile with no API token and a self-signed
  certificate. It is **not** a substitute for a certification run against the hosted suite,
  and its exports are not a submission package.
- Modules skipped as handoffs (see [handoff.md](handoff.md)) did not run. If any of them
  are in scope for the certification, they must be completed — with a wallet stub or by
  hand — before the result can be submitted.
- A green local run says "no known regression against the committed config", which is
  exactly what CI needs and strictly less than certification needs.
