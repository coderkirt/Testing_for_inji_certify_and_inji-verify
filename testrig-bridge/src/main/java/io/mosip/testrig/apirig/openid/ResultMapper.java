package io.mosip.testrig.apirig.openid;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * Reads the runner's results.json into the model the TestNG/Extent layer uses.
 *
 * Extra fields are additive: a results.json produced by an older runner still
 * loads, it simply carries less evidence.
 */
public final class ResultMapper {
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private ResultMapper() {
    }

    public static ConformanceRun load(Path resultsFile) throws IOException {
        JsonNode root = MAPPER.readTree(Files.readAllBytes(resultsFile));
        ConformanceRun run = new ConformanceRun();
        run.mode = text(root, "mode");
        run.driver = text(root, "driver");
        run.runId = text(root, "runId");
        run.benchmarkMet = root.path("benchmarkMet").asBoolean(true);
        run.benchmarkReasons = textList(root.path("benchmarkReasons"));
        run.benchmarkChecks = checkList(root.path("benchmarkChecks"));

        JsonNode summary = root.path("summary");
        run.passed = intValue(summary, "passed");
        run.failed = intValue(summary, "failed");
        run.skipped = intValue(summary, "skipped");
        run.gradedFailures = intValue(summary, "gradedFailures");
        run.toleratedFailures = intValue(summary, "toleratedFailures");
        run.handoffSkips = intValue(summary, "handoffSkips");
        run.unexpectedFailures = intValue(summary, "unexpectedFailures");
        run.moduleUnexpectedFailures = intValue(summary, "moduleUnexpectedFailures");
        run.conditionUnexpectedFailures = intValue(summary, "conditionUnexpectedFailures");
        run.unexpectedWarnings = intValue(summary, "unexpectedWarnings");
        run.unexpectedSkips = intValue(summary, "unexpectedSkips");
        run.staleExpectations = intValue(summary, "staleExpectations");
        run.errors = intValue(summary, "errors");
        run.totalModules = intValue(summary, "total");

        JsonNode conditions = summary.path("conditions");
        run.successConditions = intValue(conditions, "SUCCESS");
        run.warningConditions = intValue(conditions, "WARNING");
        run.failureConditions = intValue(conditions, "FAILURE");

        JsonNode metrics = root.path("benchmarkMetrics");
        run.passRate = metrics.path("passRate").asDouble(0.0);
        run.conditionSuccessRate = metrics.path("conditionSuccessRate").asDouble(0.0);
        if (run.gradedFailures == 0 && summary.has("gradedFailures") == false) {
            // Older results.json: fall back to the raw count.
            run.gradedFailures = run.failed;
        }

        List<ModuleResult> modules = new ArrayList<>();
        for (JsonNode plan : root.path("plans")) {
            String component = text(plan, "component");
            String planName = text(plan, "planName");
            String planId = text(plan, "planId");
            String configFile = text(plan, "configFile");
            for (JsonNode module : plan.path("modules")) {
                modules.add(readModule(module, component, planName, planId, configFile));
            }
        }
        run.modules = Collections.unmodifiableList(modules);
        return run;
    }

    private static ModuleResult readModule(
            JsonNode node, String component, String planName, String planId, String configFile) {
        ModuleResult item = new ModuleResult();
        item.component = component;
        item.planName = planName;
        item.planId = planId;
        item.configFile = configFile;
        item.testModule = text(node, "testModule");
        item.testId = text(node, "testId");
        item.status = text(node, "status");
        item.result = text(node, "result");
        item.mapped = text(node, "mapped");
        item.outcome = text(node, "outcome");
        item.expectedFailure = node.path("expectedFailure").asBoolean(false);
        item.expectedSkip = node.path("expectedSkip").asBoolean(false);
        item.handoff = node.path("handoff").asBoolean(false);
        item.unexpectedSkip = node.path("unexpectedSkip").asBoolean(false);
        item.reason = text(node, "reason");

        JsonNode counts = node.path("counts");
        item.successConditions = intValue(counts, "SUCCESS");
        item.warningConditions = intValue(counts, "WARNING");
        item.failureConditions = intValue(counts, "FAILURE");
        item.logEntries = intValue(node, "logEntries");

        item.unexpectedFailures = conditions(node.path("unexpectedFailures"));
        item.unexpectedWarnings = conditions(node.path("unexpectedWarnings"));
        item.expectedFailures = conditions(node.path("expectedFailures"));
        item.absentExpectedFailures = absentConditions(node.path("expectedFailuresDidNotHappen"));
        return item;
    }

    public static List<ModuleResult> filter(ConformanceRun run, String component) {
        if (component == null || component.isBlank() || "combined".equalsIgnoreCase(component)) {
            return run.modules;
        }
        List<ModuleResult> filtered = new ArrayList<>();
        for (ModuleResult module : run.modules) {
            if (component.equalsIgnoreCase(module.component)) {
                filtered.add(module);
            }
        }
        return filtered;
    }

    private static String text(JsonNode node, String field) {
        JsonNode value = node.get(field);
        return value == null || value.isNull() ? null : value.asText();
    }

    private static int intValue(JsonNode node, String field) {
        return node.path(field).asInt(0);
    }

    private static List<String> textList(JsonNode array) {
        List<String> out = new ArrayList<>();
        if (array.isArray()) {
            for (JsonNode item : array) {
                out.add(item.asText());
            }
        }
        return out;
    }

    /** benchmarkChecks is a list of {name, ok, detail}. */
    private static List<String> checkList(JsonNode array) {
        List<String> out = new ArrayList<>();
        if (array.isArray()) {
            for (JsonNode item : array) {
                boolean ok = item.path("ok").asBoolean(false);
                out.add((ok ? "[ok] " : "[FAIL] ") + item.path("name").asText("check") + ": "
                        + item.path("detail").asText(""));
            }
        }
        return out;
    }

    private static List<ConditionDetail> conditions(JsonNode array) {
        List<ConditionDetail> out = new ArrayList<>();
        if (array.isArray()) {
            for (JsonNode item : array) {
                if (item.isTextual()) {
                    out.add(new ConditionDetail(null, item.asText()));
                } else {
                    out.add(new ConditionDetail(text(item, "current_block"), text(item, "src")));
                }
            }
        }
        return out;
    }

    /** absentExpectedFailures is written as plain strings by the runner. */
    private static List<ConditionDetail> absentConditions(JsonNode array) {
        return conditions(array);
    }
}
