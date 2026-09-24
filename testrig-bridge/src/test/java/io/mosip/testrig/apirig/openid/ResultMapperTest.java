package io.mosip.testrig.apirig.openid;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import org.testng.Assert;
import org.testng.SkipException;
import org.testng.annotations.Test;

/**
 * The module is deliberately not loaded through the suite base class: these
 * tests must run with no stack, no suite and no network.
 */
public class ResultMapperTest {

    private static final String FULL_DOCUMENT = "{"
            + "\"mode\":\"certify\","
            + "\"driver\":\"rest-api\","
            + "\"runId\":\"certify-1767225600\","
            + "\"benchmarkMet\":false,"
            + "\"benchmarkReasons\":[\"1 unexpected failure(s)\"],"
            + "\"benchmarkChecks\":["
            + "{\"name\":\"minPassRate\",\"ok\":false,\"detail\":\"pass rate 0.00% < minPassRate 100.00%\"},"
            + "{\"name\":\"unexpectedFailures\",\"ok\":false,\"detail\":\"1 unexpected failure(s)\"}"
            + "],"
            + "\"benchmarkMetrics\":{\"passRate\":0.0,\"conditionSuccessRate\":0.75},"
            + "\"summary\":{"
            + "\"passed\":0,\"failed\":1,\"gradedFailures\":1,\"skipped\":2,\"toleratedFailures\":1,"
            + "\"handoffSkips\":1,\"unexpectedFailures\":1,\"moduleUnexpectedFailures\":1,"
            + "\"conditionUnexpectedFailures\":0,\"unexpectedWarnings\":1,\"unexpectedSkips\":0,"
            + "\"staleExpectations\":0,\"errors\":0,\"total\":3,"
            + "\"conditions\":{\"SUCCESS\":9,\"WARNING\":1,\"FAILURE\":2}"
            + "},"
            + "\"plans\":[{"
            + "\"component\":\"certify\","
            + "\"planName\":\"oid4vci-1_0-issuer-test-plan\","
            + "\"planId\":\"CBk3t95rzAZe4\","
            + "\"configFile\":\"issuer-plan.json\","
            + "\"modules\":["
            + "{"
            + "\"testModule\":\"oid4vci-1_0-issuer-happy-flow\","
            + "\"testId\":\"t1\","
            + "\"status\":\"FINISHED\",\"result\":\"FAILED\",\"mapped\":\"FAIL\",\"outcome\":\"FINISHED\","
            + "\"counts\":{\"SUCCESS\":7,\"WARNING\":1,\"FAILURE\":1},"
            + "\"logEntries\":9,"
            + "\"unexpectedFailures\":[{\"current_block\":\"Credential endpoint\",\"src\":\"ValidateSignature\"}],"
            + "\"unexpectedWarnings\":[{\"current_block\":\"Token endpoint\",\"src\":\"OptionalHeader\"}],"
            + "\"expectedFailures\":[],"
            + "\"expectedFailuresDidNotHappen\":[\"Credential endpoint / StaleRule\"]"
            + "},"
            + "{"
            + "\"testModule\":\"oid4vci-1_0-issuer-deferred\","
            + "\"status\":\"WAITING\",\"result\":null,\"mapped\":\"SKIP\",\"outcome\":\"WAITING\","
            + "\"handoff\":true,\"expectedSkip\":true,"
            + "\"reason\":\"suite is waiting for a wallet\""
            + "},"
            + "{"
            + "\"testModule\":\"oid4vci-1_0-issuer-client-attestation\","
            + "\"status\":\"FINISHED\",\"result\":\"FAILED\",\"mapped\":\"SKIP\","
            + "\"expectedFailure\":true,\"reason\":\"known gap\""
            + "}"
            + "]}]}";

    private static Path writeTemp(String json) throws Exception {
        Path file = Files.createTempFile("results", ".json");
        Files.write(file, json.getBytes(StandardCharsets.UTF_8));
        return file;
    }

    @Test
    public void parsesCountersAndMetrics() throws Exception {
        ConformanceRun run = ResultMapper.load(writeTemp(FULL_DOCUMENT));

        Assert.assertEquals(run.mode, "certify");
        Assert.assertEquals(run.driver, "rest-api");
        Assert.assertFalse(run.benchmarkMet);
        Assert.assertEquals(run.benchmarkReasons.size(), 1);
        Assert.assertEquals(run.benchmarkChecks.size(), 2);
        Assert.assertEquals(run.passed, 0);
        Assert.assertEquals(run.failed, 1);
        Assert.assertEquals(run.gradedFailures, 1);
        Assert.assertEquals(run.skipped, 2);
        Assert.assertEquals(run.toleratedFailures, 1);
        Assert.assertEquals(run.handoffSkips, 1);
        Assert.assertEquals(run.unexpectedFailures, 1);
        Assert.assertEquals(run.unexpectedWarnings, 1);
        Assert.assertEquals(run.totalModules, 3);
        Assert.assertEquals(run.successConditions, 9);
        Assert.assertEquals(run.conditionSuccessRate, 0.75, 0.0001);
        Assert.assertEquals(run.gradedModules(), 1);
    }

    @Test
    public void parsesConditionDetailAndHandoff() throws Exception {
        ConformanceRun run = ResultMapper.load(writeTemp(FULL_DOCUMENT));

        ModuleResult failing = run.modules.get(0);
        Assert.assertEquals(failing.mapped, "FAIL");
        Assert.assertEquals(failing.failureConditions, 1);
        Assert.assertEquals(failing.unexpectedFailures.size(), 1);
        Assert.assertEquals(failing.unexpectedFailures.get(0).currentBlock, "Credential endpoint");
        Assert.assertEquals(failing.unexpectedFailures.get(0).src, "ValidateSignature");
        Assert.assertEquals(failing.absentExpectedFailures.size(), 1);
        Assert.assertEquals(failing.absentExpectedFailures.get(0).src, "Credential endpoint / StaleRule");
        Assert.assertTrue(failing.evidenceSummary().contains("Credential endpoint / ValidateSignature"));
        Assert.assertTrue(failing.evidenceSummary().contains("did not happen"));

        ModuleResult handoff = run.modules.get(1);
        Assert.assertTrue(handoff.handoff);
        Assert.assertTrue(handoff.expectedSkip);
        Assert.assertEquals(handoff.outcome, "WAITING");

        ModuleResult tolerated = run.modules.get(2);
        Assert.assertTrue(tolerated.expectedFailure);
        Assert.assertEquals(tolerated.mapped, "SKIP");

        Assert.assertEquals(run.failures().size(), 1);
        Assert.assertEquals(run.handoffModules().size(), 1);
    }

    @Test
    public void filterKeepsOnlyTheRequestedComponent() throws Exception {
        ConformanceRun run = ResultMapper.load(writeTemp(FULL_DOCUMENT));
        Assert.assertEquals(ResultMapper.filter(run, "certify").size(), 3);
        Assert.assertEquals(ResultMapper.filter(run, "verify").size(), 0);
        Assert.assertEquals(ResultMapper.filter(run, "combined").size(), 3);
        Assert.assertEquals(ResultMapper.filter(run, null).size(), 3);
    }

    @Test
    public void gatePassesWhenTheBenchmarkIsMet() throws Exception {
        ConformanceRun run = ResultMapper.load(writeTemp(FULL_DOCUMENT));
        run.benchmarkMet = true;
        BenchmarkGate.assertMet(run);
    }

    @Test
    public void gateFailureCarriesMetricsAndChecks() throws Exception {
        ConformanceRun run = ResultMapper.load(writeTemp(FULL_DOCUMENT));
        try {
            BenchmarkGate.assertMet(run);
            Assert.fail("gate should have failed");
        } catch (AssertionError expected) {
            String message = String.valueOf(expected.getMessage());
            Assert.assertTrue(message.contains("unexpected failure"), message);
            Assert.assertTrue(message.contains("pass rate"), message);
            Assert.assertTrue(message.contains("minPassRate"), message);
            Assert.assertTrue(message.contains("handoff"), message);
        }
    }

    @Test
    public void gateFailsWhenNoResultsWereLoaded() {
        try {
            BenchmarkGate.assertMet(null);
            Assert.fail("gate should have failed");
        } catch (AssertionError expected) {
            Assert.assertTrue(String.valueOf(expected.getMessage()).contains("No conformance results"));
        }
    }

    /**
     * Cross-checks the mapper against the same fixture the Python runner tests
     * use, so the two sides of the bridge cannot drift apart silently.
     */
    @Test
    public void readsTheRunnerTestFixture() throws Exception {
        Path[] candidates = {
            Path.of("..", "runner", "tests", "fixtures", "results-with-expected-failures.json"),
            Path.of("runner", "tests", "fixtures", "results-with-expected-failures.json"),
        };
        Path fixture = null;
        for (Path candidate : candidates) {
            if (Files.exists(candidate)) {
                fixture = candidate;
                break;
            }
        }
        if (fixture == null) {
            throw new SkipException(
                "runner/tests/fixtures not present - this module has been copied out of the harness repo");
        }

        ConformanceRun run = ResultMapper.load(fixture);
        Assert.assertEquals(run.passed, 2);
        Assert.assertEquals(run.failed, 0);
        Assert.assertEquals(run.toleratedFailures, 1);
        Assert.assertEquals(run.handoffSkips, 1);
        Assert.assertEquals(run.unexpectedFailures, 0);
        Assert.assertEquals(run.modules.size(), 4);
        Assert.assertEquals(run.handoffModules().size(), 1);
        Assert.assertEquals(run.successConditions, 49);
        Assert.assertTrue(run.benchmarkMet);
    }
}
