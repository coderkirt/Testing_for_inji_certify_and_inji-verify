package io.mosip.testrig.apirig.openid;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public class ConformanceRun {
    public String mode;
    public String driver;
    public String runId;
    public boolean benchmarkMet = true;
    public List<String> benchmarkReasons = Collections.emptyList();
    public List<String> benchmarkChecks = Collections.emptyList();

    // Summary counters. "failed" is the raw module count; gradedFailures is
    // what the pass rate is computed over, i.e. excluding tolerated failures.
    public int passed;
    public int failed;
    public int skipped;
    public int gradedFailures;
    public int toleratedFailures;
    public int handoffSkips;
    public int unexpectedFailures;
    public int moduleUnexpectedFailures;
    public int conditionUnexpectedFailures;
    public int unexpectedWarnings;
    public int unexpectedSkips;
    public int staleExpectations;
    public int errors;
    public int totalModules;

    // Condition counts across the whole run.
    public int successConditions;
    public int warningConditions;
    public int failureConditions;

    public double passRate;
    public double conditionSuccessRate;

    public List<ModuleResult> modules = Collections.emptyList();

    public List<ModuleResult> failures() {
        List<ModuleResult> out = new ArrayList<>();
        for (ModuleResult module : modules) {
            if ("FAIL".equalsIgnoreCase(module.mapped)) {
                out.add(module);
            }
        }
        return out;
    }

    public List<ModuleResult> handoffModules() {
        List<ModuleResult> out = new ArrayList<>();
        for (ModuleResult module : modules) {
            if (module.handoff) {
                out.add(module);
            }
        }
        return out;
    }

    public int gradedModules() {
        return passed + gradedFailures;
    }

    public String summaryLine() {
        return String.format(
                "%s run: %d passed, %d failed (%d graded), %d skipped (%d handoff), "
                        + "%d unexpected failure(s), pass rate %.2f%%",
                mode == null ? "conformance" : mode, passed, failed, gradedFailures, skipped,
                handoffSkips, unexpectedFailures, passRate * 100.0);
    }
}
