# Troubleshooting

Every entry below is a failure this harness can actually produce, with the message you will
see and the smallest thing that fixes it.

## The entry point fails before any conformance runs

| Message | Cause | Fix |
| --- | --- | --- |
| `error during connect: ... dockerDesktopLinuxEngine` | Docker is installed but the daemon is not running | start Docker Desktop and re-run; `docker compose version` should answer first |
| `Timed out waiting for Inji Certify (issuer metadata) (http://127.0.0.1:8091/...)` | Certify is not serving metadata yet, or its port mapping differs | `docker compose -f compose/docker-compose.yml logs --tail=100 certify`, then check `CERTIFY_NGINX_PORT` in `compose/.env` |
| `Timed out waiting for Inji Verify (service health)` | same, for `VERIFY_HOST_PORT` and `/v1/verify/actuator/health` | `docker compose ... logs verify-service` |
| `Timed out waiting for OpenID conformance suite` | suite or Mongo not up | `docker compose ... ps`; the `server` container waits on `mongodb` |

`docker compose up -d --wait` already fails on a crash-looping container, so a service that
cannot reach healthy fails here rather than as confusing conformance noise later. Raise
`HEALTH_TIMEOUT` (default 600s) on a cold machine.

## The suite is unreachable from the host

The runner talks to `https://localhost.emobix.co.uk:8443`, which must resolve to
`127.0.0.1`. Add the entry once:

```
127.0.0.1 localhost.emobix.co.uk      # /etc/hosts or C:\Windows\System32\drivers\etc\hosts
```

Symptoms are a connection error, or a certificate warning in a browser. The runner accepts
the suite's self-signed certificate (`verify=False`) for the local stack; browsers still warn.

## `Suite did not become ready within 360s`

`GET api/plan?length=1` never returned 200. Almost always Mongo: the suite answers but its
datastore does not. Check `docker compose ... logs mongodb server`. Use `--skip-wait` only
when you know the suite is up and you want the runner to try anyway.

## Plan create fails

```
create plan 'oid4vci-1_0-issuer-test-plan' failed: HTTP 400 <suite message>
```

The runner surfaces the suite's own error text instead of a bare status, so read it. The two
common causes:

- **Wrong plan name for this suite build.** Check `GET api/plan/available`, or run
  `./scripts/run-conformance.sh --component certify --validate-plans`, which prints the
  plans this build offers and exits.
- **A variant key this build does not offer.** `--validate-plans` lists the unknown keys
  explicitly. Start from `runner/configs/issuer-variant.json` /
  `verifier-variant.json` rather than inventing keys.

## A module fails with `TIMEOUT`

`module did not finish within 600s`. Either the module is genuinely slow (raise
`--module-timeout`, or `OIDF_MODULE_TIMEOUT`) or it is stuck against an implementation that
never answers.

If the suite state was `WAITING`, this is **not** the message you get — that becomes a
documented handoff skip. See [handoff.md](handoff.md).

## A module is reported as `CONFIGURED`, or "is CONFIGURED - starting it explicitly" appears

The module did not auto-start. The runner starts it (`--auto-start`, the default) like
`run-test-plan.py` does. If it still cannot start, the module is recorded as
`SKIP` with `outcome: "CONFIGURED"` and the reason says so — it did not run, and the report
says that rather than pretending.

`--no-auto-start` disables the explicit start for comparison with the suite's own behaviour.

## Modules ran serially although `--parallel` was passed

```
Config declares alias 'inji-certify-openid-1_0' - running modules serially as run-test-plan.py does
```

The plan config declares an `alias`, and the suite cannot register one alias concurrently.
This is intentional. `--force-parallel-modules` overrides it; expect confusing failures if
the modules really do share the alias.

## TestNG reports "no conformance modules"

```
java.io.IOException: Conformance runner exited 1 without writing .../results.json
```

The runner failed before writing anything — the suite was never reached. Read the runner
output above the exception; `--skip-wait` or a wrong `--suite-url` are the usual causes.

The other variant is a stale or wrong `results.json`:

- re-run without `--official-script` (official-script mode produces no module list), or
- drop `-Dconformance.reuseResults=true` so the bridge re-runs the driver.

## `mvn test -DsuiteXmlFile=...` ran the unit test instead of the suite

Surefire ignores `-DsuiteXmlFile` unless the profile is active. Always:

```bash
mvn -f testrig-bridge/pom.xml -Pconformance-suite test \
  -DsuiteXmlFile=src/test/resources/testng-certify.xml \
  -Dconformance.results=../results/certify/results.json \
  -Dconformance.component=certify
```

Without `-Pconformance-suite` you get `ResultMapperTest` and a green build that never
touched the conformance suite. The wrapper scripts do this correctly.

## `Could not read .../results/${conformance.results}`

An unset `-Dconformance.results` used to be injected as the literal string
`${conformance.results}`. The pom now defines empty defaults for
`conformance.results`/`component`/`repoRoot`, so the bridge either runs the driver itself or
tells you which argument is missing.

## The gate fails with "0 adjudicated module(s)"

The run produced no verdicts: every module was skipped. Usually a plan whose modules all
parked in `WAITING` (all handoffs) or a plan whose modules were all filtered out. Read
`summary.skippedModules` and `summary.handoffSkips` in `results.json` — the report tells you
which of the two it was.

`passRate` is `1.0` over an empty denominator by definition, so a gate that looks
"passed with nothing graded" is a config smell, not a bug. `requiredModules` is how you make
that impossible; see below.

## "missing required modules" or "did not produce a verdict"

`requiredModules` in `benchmark.json` lists modules that must be graded. A selective run
(`--only`) that filters one of them out fails this check on purpose — that is the guard that
stops a filtered run from masquerading as a full one. Either select it or change
`requiredModules`.

## "expected failure(s) did not happen - expected-failures.json is stale"

A rule in `expected-failures.json` stopped matching, which usually means the gap was fixed.
Remove the stale rule (the gate stays red until you do, so the file cannot rot silently).

## "N unexpected failure(s)" although every module says PASSED

Some module reported `PASSED` while emitting failing conditions. That is the false green the
condition analysis exists to catch. Look at the module's `unexpectedFailures` array in
`results.json` — each entry names the conformance block and the check. Fix the product, or
declare it as an expected failure in `expected-failures.json` with a reason.

## The stack came up before but now Certify is broken

- Schema seed: first boot only runs `certify/certify_init.sql` and `verify/init.sql`.
  Recreate the volumes after changing either: `docker compose -f compose/docker-compose.yml down -v`.
- If Certify does not boot against the vendored schema at all, `compose/.env.example`
  documents the fallback pin (the 0.14.x image the seed came from) next to `CERTIFY_IMAGE`.
  Keep `.env` and `.env.example` in step so this stays reproducible.
- Issuer identity: `CERTIFY_ISSUER_URL` must be exactly the issuer URL Certify advertises.
  If metadata fetch fails across the board, compare the two before debugging anything else.

## Ports already in use

The compose stack publishes `8443` (suite), `8090`/`8091` (Certify), `8080`/`3000` (Verify),
`5432`/`5433` (databases). If something else is listening — another harness, another dev
server — change the `*_PORT` values in `compose/.env`. The entry points read the ports from
that file, so health checks follow automatically.

## Report publish problems

```
push-reports-to-s3 is off - skipping report publish
```

That is not an error: publishing is opt-in. To turn it on, set `push-reports-to-s3: true`
in `runner/configs/s3.json` (or `PUSH_REPORTS_TO_S3=true` in the environment, or
`--publish-reports` on the entry point).

| Message | Fix |
| --- | --- |
| `Report publish requested but missing: s3-user-key, s3-user-secret` | fill in the credentials; the same keys the api-testrig uses, see [runner/README.md](../runner/README.md) |
| `Report publish failed: ... 403 ...` | credentials are wrong, or the region/host does not match the bucket |
| TLS error against a MinIO endpoint | `python runner/s3_upload.py ... --insecure`, or install the MinIO certificate |

The publisher writes to the same bucket name as the api-testrig (`automationtests` by
default) at `<s3-prefix>/<run-id>/...`, and a publish failure never masks the conformance
result — check the exit code, not just the last line of output.

## `compose/.env` looks wrong

The entry points copy `.env.example` to `.env` on first run. If you have an old `.env`, keys
added since (for example `CERTIFY_CREDENTIAL_CONFIGURATION_ID`, the S3 block) are missing
because the copy only happens when the file is absent. Compare the two files, or delete
`.env` and let it be recreated.
