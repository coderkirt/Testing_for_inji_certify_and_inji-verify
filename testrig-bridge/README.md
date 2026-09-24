# api-testrig bridge

Drop-in TestNG classes that turn the runner's `results.json` into exactly the TestNG +
Extent reporting the MOSIP api-testrig already publishes — one TestNG result per conformance
module, with the suite's own evidence attached.

| Class | Role |
| --- | --- |
| `openid/ResultMapper` | `results.json` → `ConformanceRun` with one `ModuleResult` per module |
| `openid/OpenIDConformanceSupport` | `@BeforeSuite` run/fetch, `conformanceModules` data provider, per-module assert, `@AfterSuite` gate |
| `injicertify/testscripts/OpenIDConformanceTest` | the Certify suite entry point |
| `injiverify/testscripts/OpenIDConformanceTest` | the Verify suite entry point |
| `openid/CombinedOpenIDConformanceTest` | both plans in one report |
| `openid/BenchmarkGate` | fails the suite when the runner's benchmark was not met |
| `openid/ExtentReportListener` | the Extent Spark report, with condition-level evidence per node |

## Two tiers, deliberately

```bash
# Tier 1 - unit tests only. No stack, no suite, seconds.
mvn -f testrig-bridge/pom.xml test

# Tier 2 - the TestNG suite. The profile is REQUIRED.
mvn -f testrig-bridge/pom.xml -Pconformance-suite test \
  -DsuiteXmlFile=src/test/resources/testng-certify.xml \
  -Dconformance.results=../results/certify/results.json \
  -Dconformance.component=certify
```

`-Pconformance-suite` is not optional: surefire ignores `-DsuiteXmlFile` without it and
silently runs the unit test instead, which is a green build that never touched the
conformance suite.

Each suite XML runs `ResultMapperTest` **first**, so a broken mapper is reported before it
maps anything, and both test elements accumulate into **one** Extent report
(`target/extent/OpenIDConformance-<mode>.html`).

## Prove it without Docker

Tier 2 does not need a stack if you point it at the committed fixture:

```bash
mvn -f testrig-bridge/pom.xml -Pconformance-suite test \
  -DsuiteXmlFile=src/test/resources/testng-combined.xml \
  -Dconformance.results=../runner/tests/fixtures/results-with-expected-failures.json \
  -Dconformance.component=combined
# Total tests run: 11, Passes: 9, Skips: 2
```

The two skips are a documented expected failure and a declared skip, shown as skips rather
than as passes — which is the whole point of the bridge.

## System properties

| Property | Effect |
| --- | --- |
| `conformance.results` | use this `results.json` instead of running the driver (env: `CONFORMANCE_RESULTS`) |
| `conformance.component` | `certify`, `verify` or `combined`; selects which modules the suite reports |
| `conformance.repoRoot` | where `runner/run_conformance.py` lives (env: `CONFORMANCE_REPO_ROOT`); otherwise walks up from the working directory |
| `conformance.reuseResults` | reuse an existing `results.json` instead of re-running the driver |
| `conformance.python` | python executable (env: `PYTHON`); defaults to `python` on Windows, `python3` elsewhere |
| `env.endpoint` | the api-testrig endpoint; forwarded as the issuer URL (env: `ENV_ENDPOINT`, `CERTIFY_ISSUER_URL`) |
| `verify.endpoint` | verifier endpoint (env: `VERIFY_ENDPOINT`) |
| `conformance.server`, `conformance.token` | suite URL and bearer token |
| `conformance.expectedFailures`, `conformance.expectedSkips`, `conformance.benchmark` | override the runner's config files |
| `conformance.baseline` | benchmark baseline to diff against |
| `conformance.moduleTimeout`, `conformance.handoffGrace` | per-module budget and handoff grace |
| `conformance.parallel`, `conformance.autoStart` | booleans passed through to the runner |
| `conformance.only`, `conformance.skip` | comma-separated wildcards for selective execution |
| `emailable.report2.name` | Extent report name; the suite sets `OpenIDConformance-<component>` |

When `conformance.results` is not set, `ConformanceRunner` shells out to
`runner/run_conformance.py` with the properties above, inherits the console, and waits up to
6 hours. A **non-zero exit is expected** when the benchmark fails — `results.json` is still
authoritative, and only a missing `results.json` is treated as an error.

## Verdict semantics

| Module state | TestNG outcome |
| --- | --- |
| `PASS` | pass, with the condition summary in Extent |
| `FAIL` | failure, with the evidence (block + check) in the Extent node |
| `SKIP`, or `expectedSkip` / `handoff` | `SkipException` carrying the reason — never a pass |
| `expectedFailure` still mapped `FAIL` | `SkipException` (the gap is declared, not hidden) |
| benchmark not met | `@AfterSuite` `BenchmarkGate` fails the suite with every failing check listed |

A configuration failure during `@BeforeSuite` (for example the runner never producing
`results.json`) is reported too: that is the most important failure in the suite, and the
listener implements `IConfigurationListener` so it cannot be missed.

## Drop into mosip-functional-tests

1. Copy `src/main/java/io/mosip/testrig/apirig/openid/` into the api-testrig commons (or into
   each module, keeping the package name).
2. Copy `injicertify/testscripts/OpenIDConformanceTest.java` into the Inji Certify testrig.
3. Copy `injiverify/testscripts/OpenIDConformanceTest.java` into the Inji Verify testrig.
4. Add the matching TestNG XML fragment to each module suite — listener, then
   `ResultMapperTest`, then `OpenIDConformanceTest`, as in `src/test/resources/testng-*.xml`.
5. Point `conformance.repoRoot` (or `CONFORMANCE_REPO_ROOT`) at this harness so the Python
   runner is found, and keep the dependency versions in step with the module's
   `testng` / `jackson-databind` / `extentreports` — the bridge adds no other dependency.

Each module stays an independent gate, which is the requirement: a verifier regression must
not red out the issuer suite. Use `CombinedOpenIDConformanceTest` only for the optional
cross-module view.

`ResultMapperTest` reads `runner/tests/fixtures/results-with-expected-failures.json`, the
same fixture the Python tests use, so the JSON contract between the two languages is tested
from both sides. Keep the fixture in `../runner/tests/fixtures/`, or set
`conformance.repoRoot` if the harness lives elsewhere.
