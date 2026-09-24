# api-testrig bridge

Drop-in TestNG classes that turn `results.json` from the Python runner into the same TestNG / Extent reports the MOSIP api-testrig already publishes.

## Standalone

```bash
# After the runner has written results/certify/results.json
mvn -f testrig-bridge/pom.xml test \
  -DsuiteXmlFile=src/test/resources/testng-certify.xml \
  -Dconformance.results=../results/certify/results.json \
  -Dconformance.component=certify
```

If `conformance.results` is omitted, `OpenIDConformanceTest` shells out to `runner/run_conformance.py` using the same `env.endpoint` / `ENV_ENDPOINT` the testrig already uses.

## Drop into mosip-functional-tests

1. Copy `src/main/java/io/mosip/testrig/apirig/openid/` into the api-testrig commons or each module.
2. Copy `injicertify/testscripts/OpenIDConformanceTest.java` into the Inji Certify testrig.
3. Copy `injiverify/testscripts/OpenIDConformanceTest.java` into the Inji Verify testrig.
4. Add the matching TestNG XML fragment to each module suite.
5. Point `CONFORMANCE_REPO_ROOT` (or keep this harness as a sibling checkout) so the Python runner is found.

Each module remains an independent gate. Use `CombinedOpenIDConformanceTest` only for the optional cross-module badge.
