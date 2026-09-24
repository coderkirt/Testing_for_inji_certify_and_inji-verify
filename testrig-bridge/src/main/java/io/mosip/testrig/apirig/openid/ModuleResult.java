package io.mosip.testrig.apirig.openid;

import java.util.ArrayList;
import java.util.List;
import java.util.stream.Collectors;

public class ModuleResult {
    public String component;
    public String planName;
    public String planId;
    public String configFile;
    public String testModule;
    public String testId;
    public String status;
    public String result;
    public String mapped;
    public String outcome;
    public boolean expectedFailure;
    public boolean expectedSkip;
    public boolean handoff;
    public boolean unexpectedSkip;
    public String reason;

    // Condition level evidence from api/log/{id}.
    public int successConditions;
    public int warningConditions;
    public int failureConditions;
    public int logEntries;
    public List<ConditionDetail> unexpectedFailures = new ArrayList<>();
    public List<ConditionDetail> unexpectedWarnings = new ArrayList<>();
    public List<ConditionDetail> expectedFailures = new ArrayList<>();
    public List<ConditionDetail> absentExpectedFailures = new ArrayList<>();

    public String displayName() {
        return (component == null ? "" : component + " / ") + testModule;
    }

    public boolean hasConditionData() {
        return logEntries > 0
                || successConditions + warningConditions + failureConditions > 0
                || !unexpectedFailures.isEmpty()
                || !unexpectedWarnings.isEmpty();
    }

    public String conditionSummary() {
        return String.format(
                "%d SUCCESS / %d WARNING / %d FAILURE condition(s) across %d log entr%s",
                successConditions, warningConditions, failureConditions, logEntries,
                logEntries == 1 ? "y" : "ies");
    }

    /** Human readable evidence for the report; empty when there is nothing to say. */
    public String evidenceSummary() {
        List<String> lines = new ArrayList<>();
        if (hasConditionData()) {
            lines.add(conditionSummary());
        }
        lines.addAll(describe("Unexpected failures", unexpectedFailures));
        lines.addAll(describe("Unexpected warnings", unexpectedWarnings));
        lines.addAll(describe("Tolerated failures (expected-failures.json)", expectedFailures));
        lines.addAll(describe("Expected failures that did not happen", absentExpectedFailures));
        if (unexpectedSkip) {
            lines.add("Module was unexpectedly skipped");
        }
        if (handoff) {
            lines.add("Blocked on a wallet handoff - see docs/handoff.md");
        }
        return String.join("\n", lines);
    }

    private static List<String> describe(String label, List<ConditionDetail> details) {
        if (details == null || details.isEmpty()) {
            return List.of();
        }
        String joined = details.stream().map(ConditionDetail::toString).collect(Collectors.joining("; "));
        return List.of(label + ": " + joined);
    }

    public String reasonOr(String fallback) {
        return reason == null || reason.isBlank() ? fallback : reason;
    }
}
