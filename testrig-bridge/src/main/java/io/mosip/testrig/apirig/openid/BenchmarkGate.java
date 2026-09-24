package io.mosip.testrig.apirig.openid;

import org.testng.Assert;

public final class BenchmarkGate {
    private BenchmarkGate() {
    }

    public static void assertMet(ConformanceRun run) {
        if (run == null) {
            Assert.fail("No conformance results were loaded");
        }
        if (!run.benchmarkMet) {
            Assert.fail("Conformance benchmark not met: " + String.join("; ", run.benchmarkReasons));
        }
    }
}
