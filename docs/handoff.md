# Per-component handoff

Some OpenID4VP verifier modules wait for a wallet to complete a presentation. The suite
parks the module in `WAITING` until something sends it a valid OpenID4VP request. This page
is about how the harness handles that honestly instead of confusing it with a hang.

## What the runner does with a `WAITING` module

Nothing waits forever. The transcript is:

1. `wait_for_settled` polls `api/info/{id}` and sees `WAITING`.
2. With `--handoff-grace 0` (the default) it returns `WAITING` **immediately**; with a
   larger grace it keeps polling that long first, for a wallet that takes a few seconds to
   answer.
3. The module is recorded as `mapped: "SKIP"` with `handoff: true`, `expectedSkip: true`,
   `outcome: "WAITING"`, and a reason pointing here or at `expected-skips.json`.
4. In TestNG it becomes a `SkipException` with that reason, so it is visibly skipped and
   never counted as a pass.
5. The rest of the plan keeps running, and the plan still exports.

Before this behaviour existed, a single `WAITING` module consumed the whole per-module
timeout and then threw, which aborted the plan — which is why `--component verify` and
`--combined` never completed. That regression is pinned by a test that runs a `WAITING`
module with a 3-second timeout and asserts a prompt skip.

Handoff skips are **not** failures by default (`failOnHandoff: false` in
`benchmark.json`). Set it to `true` when you want the gate to insist that everything ran
unattended.

## Inji Certify (issuer)

Most OpenID4VCI modules in `oid4vci-1_0-issuer-test-plan` — issuer metadata, credential
offer, pre-authorized code, credential endpoint — are unattended, and they are the ones
worth gating on. Anything that needs a genuine interactive authorization-code flow with a
real user will either use the mocked authorization server configured in
`compose/certify/config/certify-csvdp-farmer.properties`, or it should be listed in
`runner/configs/expected-skips.json` with a reason.

Keep authorization-code / HAIP variants in `issuer-variant.json` only once Certify is
configured for that grant. A variant Certify cannot serve produces failures that look like
product bugs but are not.

## Inji Verify (verifier)

When a module is `WAITING`, you have three options, in increasing order of effort:

1. **Skip it deliberately.** Add the module to `runner/configs/expected-skips.json` so it
   is never started, and record why in the same commit. This is what the committed config
   expects for interactive flows with no stubbed wallet.
2. **Complete it by hand, once.** The suite exposes the request for the current alias:

   - open the suite session for the plan and copy the `openid4vp://` link, or
   - point Inji Verify at the suite's `authorization_endpoint` for that alias instead of a
     wallet URL,

   then let the plan finish. Raise `--handoff-grace` so the runner keeps polling while you
   do it. This is a manual step, so the pass it produces is only as good as the operator —
   it is useful for triage, not for CI.
3. **Stub the wallet.** The only real fix. A scripted wallet that answers the
   `authorization_endpoint` would turn these modules into unattended ones, and they would
   then be gateable. This is the natural next milestone for this harness.

For a device or mobile wallet on the same machine, tunnel Inji Verify (`ngrok` or similar)
and set `VERIFY_PUBLIC_HOST` in `compose/.env` to the tunnel host, so the wallet can reach
the service. `compose/verify/config.json` also lists the web wallet base URL
(`WebWallets[].walletBaseUrl`), which is what the Verify UI links out to.

## Combined runs

`--combined` runs both plans into one `results.json` and one Extent report.

- A handoff skip on Verify never fails the Certify side: each module carries its own
  verdict, and the summary counts `handoffSkips` separately.
- An **unexpected** failure on either side fails the combined gate, with the module name
  and its conformance block in `benchmarkReasons`.
- The combined report is the one to show a reviewer: it lists every module of both plans
  with its evidence, and says explicitly which ones did not run unattended.
