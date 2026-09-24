package io.mosip.testrig.apirig.openid;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import org.testng.Assert;
import org.testng.annotations.Test;

public class ResultMapperTest {
    @Test
    public void mapsPassFailSkipAndBenchmark() throws Exception {
        String json = "{"
                + "\"mode\":\"combined\","
                + "\"benchmarkMet\":false,"
                + "\"benchmarkReasons\":[\"2 unexpected failure(s)\"],"
                + "\"summary\":{\"passed\":1,\"failed\":1,\"skipped\":1,\"unexpectedFailures\":1},"
                + "\"plans\":[{"
                + "\"component\":\"certify\","
                + "\"planName\":\"oid4vci-1_0-issuer-test-plan\","
                + "\"planId\":\"abc\","
                + "\"modules\":["
                + "{\"testModule\":\"issuer-metadata\",\"result\":\"PASSED\",\"mapped\":\"PASS\"},"
                + "{\"testModule\":\"issuer-happy\",\"result\":\"FAILED\",\"mapped\":\"FAIL\"},"
                + "{\"testModule\":\"issuer-handoff\",\"result\":\"SKIPPED\",\"mapped\":\"SKIP\",\"expectedSkip\":true}"
                + "]}]}";
        Path file = Files.createTempFile("results", ".json");
        Files.write(file, json.getBytes(StandardCharsets.UTF_8));
        ConformanceRun run = ResultMapper.load(file);
        Assert.assertEquals(run.modules.size(), 3);
        Assert.assertEquals(ResultMapper.filter(run, "certify").size(), 3);
        Assert.assertFalse(run.benchmarkMet);
        try {
            BenchmarkGate.assertMet(run);
            Assert.fail("gate should fail");
        } catch (AssertionError expected) {
            Assert.assertTrue(expected.getMessage().contains("unexpected"));
        }
    }
}
