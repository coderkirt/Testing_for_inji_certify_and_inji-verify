package io.mosip.testrig.apirig.openid;

import org.testng.Assert;

/**
 * Fails the suite when the conformance benchmark is not met.
 *
 * The gate itself is evaluated by the Python runner (runner/benchmark.py) so
 * that the same rules apply whether the run is driven from a shell or from
 * TestNG; this class only surfaces the verdict, with the metrics and the
 * individual failing checks attached so a failure is actionable from the
 * report alone.
 */
public final class BenchmarkGate {
    private BenchmarkGate() {
    }

    public static void assertMet(ConformanceRun run) {
        if (run == null) {
            Assert.fail("No conformance results were loaded");
        }
        if (run.benchmarkMet) {
            return;
        }
        StringBuilder message = new StringBuilder("Conformance benchmark not met");
        if (run.mode != null) {
            message.append(" (").append(run.mode).append(')');
        }
        message.append('\n').append(run.summaryLine());
        if (!run.benchmarkReasons.isEmpty()) {
            message.append("\nReasons:");
            for (String reason : run.benchmarkReasons) {
                message.append("\n  - ").append(reason);
            }
        }
        if (!run.benchmarkChecks.isEmpty()) {
            message.append("\nChecks:");
            for (String check : run.benchmarkChecks) {
                message.append("\n  ").append(check);
            }
        }
        Assert.fail(message.toString());
    }
}
