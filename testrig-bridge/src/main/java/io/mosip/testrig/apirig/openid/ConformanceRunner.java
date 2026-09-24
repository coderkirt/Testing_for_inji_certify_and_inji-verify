package io.mosip.testrig.apirig.openid;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.TimeUnit;

/**
 * Invokes the Python conformance runner so TestNG can own the same env.endpoint
 * the existing api-testrig already targets.
 *
 * The runner is expected to exit non-zero when the benchmark is not met. That is
 * the normal "tests failed" path, not an error: results.json is still written
 * and the bridge reports the outcome through TestNG. Only a missing
 * results.json is treated as an error here.
 */
public final class ConformanceRunner {
    private ConformanceRunner() {
    }

    public static Path ensureResults(String component) throws IOException, InterruptedException {
        String override = firstNonBlank(
                System.getProperty("conformance.results"),
                System.getenv("CONFORMANCE_RESULTS"));
        if (override != null) {
            Path path = Path.of(override);
            if (Files.exists(path)) {
                return path;
            }
        }

        Path repoRoot = detectRepoRoot();
        Path outputDir = repoRoot.resolve("results").resolve(component);
        Path results = outputDir.resolve("results.json");

        if (Files.exists(results)
                && Boolean.parseBoolean(System.getProperty("conformance.reuseResults", "false"))) {
            return results;
        }

        Path runner = repoRoot.resolve("runner").resolve("run_conformance.py");
        if (!Files.exists(runner)) {
            throw new IOException(
                    "Python conformance runner not found at " + runner
                            + ". Set -Dconformance.repoRoot or CONFORMANCE_REPO_ROOT to the harness checkout.");
        }

        Files.createDirectories(outputDir);
        List<String> command = new ArrayList<>();
        command.add(pythonExecutable());
        command.add(runner.toString());
        if ("combined".equalsIgnoreCase(component)) {
            command.add("--combined");
        } else {
            command.add("--component");
            command.add(component);
        }
        command.add("--output-dir");
        command.add(outputDir.toString());

        String envEndpoint = firstNonBlank(
                System.getProperty("env.endpoint"),
                System.getenv("ENV_ENDPOINT"),
                System.getenv("CERTIFY_ISSUER_URL"));
        if (envEndpoint != null) {
            command.add("--certify-issuer-url");
            command.add(envEndpoint);
        }

        addIfSet(command, "--verify-endpoint", firstNonBlank(
                System.getProperty("verify.endpoint"), System.getenv("VERIFY_ENDPOINT")));
        addIfSet(command, "--suite-url", firstNonBlank(
                System.getProperty("conformance.server"), System.getenv("CONFORMANCE_SERVER")));
        addIfSet(command, "--token", firstNonBlank(
                System.getProperty("conformance.token"), System.getenv("CONFORMANCE_TOKEN")));
        addIfSet(command, "--expected-failures", System.getProperty("conformance.expectedFailures"));
        addIfSet(command, "--expected-skips", System.getProperty("conformance.expectedSkips"));
        addIfSet(command, "--benchmark", System.getProperty("conformance.benchmark"));
        addIfSet(command, "--baseline", System.getProperty("conformance.baseline"));
        addIfSet(command, "--module-timeout", System.getProperty("conformance.moduleTimeout"));
        addIfSet(command, "--handoff-grace", System.getProperty("conformance.handoffGrace"));

        // Selective execution: comma separated shell wildcards, so a developer
        // can drive one module from the api-testrig without a full plan run.
        addPatterns(command, "--only", System.getProperty("conformance.only"));
        addPatterns(command, "--skip", System.getProperty("conformance.skip"));

        if (Boolean.parseBoolean(System.getProperty("conformance.parallel", "false"))) {
            command.add("--parallel");
        }
        if (Boolean.parseBoolean(System.getProperty("conformance.autoStart", "true"))) {
            command.add("--auto-start");
        }

        ProcessBuilder builder = new ProcessBuilder(command);
        builder.directory(repoRoot.toFile());
        builder.inheritIO();
        Process process = builder.start();
        boolean finished = process.waitFor(6, TimeUnit.HOURS);
        if (!finished) {
            process.destroyForcibly();
            throw new IOException("Conformance runner timed out after 6 hours");
        }
        if (!Files.exists(results)) {
            throw new IOException(
                    "Conformance runner exited " + process.exitValue()
                            + " without writing " + results + " - see the runner output above");
        }
        // A non-zero exit means the benchmark was not met (or the suite could not
        // be driven); results.json is authoritative either way.
        return results;
    }

    private static void addIfSet(List<String> command, String flag, String value) {
        if (value != null && !value.isBlank()) {
            command.add(flag);
            command.add(value);
        }
    }

    private static void addPatterns(List<String> command, String flag, String csv) {
        if (csv == null || csv.isBlank()) {
            return;
        }
        for (String pattern : csv.split(",")) {
            String trimmed = pattern.trim();
            if (!trimmed.isEmpty()) {
                command.add(flag);
                command.add(trimmed);
            }
        }
    }

    private static String pythonExecutable() {
        String configured = firstNonBlank(System.getProperty("conformance.python"), System.getenv("PYTHON"));
        if (configured != null) {
            return configured;
        }
        return isWindows() ? "python" : "python3";
    }

    private static boolean isWindows() {
        return System.getProperty("os.name", "").toLowerCase().contains("win");
    }

    private static Path detectRepoRoot() {
        String configured = firstNonBlank(
                System.getProperty("conformance.repoRoot"),
                System.getenv("CONFORMANCE_REPO_ROOT"));
        if (configured != null && !configured.isBlank()) {
            return Path.of(configured);
        }
        File here = new File(System.getProperty("user.dir"));
        File current = here;
        while (current != null) {
            if (new File(current, "runner/run_conformance.py").isFile()) {
                return current.toPath();
            }
            current = current.getParentFile();
        }
        return here.toPath();
    }

    private static String firstNonBlank(String... values) {
        for (String value : values) {
            if (value != null && !value.isBlank()) {
                return value;
            }
        }
        return null;
    }
}
