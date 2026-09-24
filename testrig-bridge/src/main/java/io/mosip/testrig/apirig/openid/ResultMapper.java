package io.mosip.testrig.apirig.openid;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

public final class ResultMapper {
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private ResultMapper() {
    }

    public static ConformanceRun load(Path resultsFile) throws IOException {
        JsonNode root = MAPPER.readTree(Files.readAllBytes(resultsFile));
        ConformanceRun run = new ConformanceRun();
        run.mode = text(root, "mode");
        run.benchmarkMet = root.path("benchmarkMet").asBoolean(true);
        run.benchmarkReasons = new ArrayList<>();
        for (JsonNode reason : root.path("benchmarkReasons")) {
            run.benchmarkReasons.add(reason.asText());
        }
        JsonNode summary = root.path("summary");
        run.passed = summary.path("passed").asInt();
        run.failed = summary.path("failed").asInt();
        run.skipped = summary.path("skipped").asInt();
        run.unexpectedFailures = summary.path("unexpectedFailures").asInt();

        List<ModuleResult> modules = new ArrayList<>();
        for (JsonNode plan : root.path("plans")) {
            String component = text(plan, "component");
            String planName = text(plan, "planName");
            String planId = text(plan, "planId");
            for (JsonNode module : plan.path("modules")) {
                ModuleResult item = new ModuleResult();
                item.component = component;
                item.planName = planName;
                item.planId = planId;
                item.testModule = text(module, "testModule");
                item.testId = text(module, "testId");
                item.status = text(module, "status");
                item.result = text(module, "result");
                item.mapped = text(module, "mapped");
                item.expectedFailure = module.path("expectedFailure").asBoolean(false);
                item.expectedSkip = module.path("expectedSkip").asBoolean(false);
                item.reason = text(module, "reason");
                modules.add(item);
            }
        }
        run.modules = Collections.unmodifiableList(modules);
        return run;
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
}
