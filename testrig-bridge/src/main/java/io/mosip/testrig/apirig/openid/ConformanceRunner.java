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
 */
public final class ConformanceRunner {
    private ConformanceRunner() {
    }

    public static Path ensureResults(String component) throws IOException, InterruptedException {
        String override = System.getProperty("conformance.results", System.getenv("CONFORMANCE_RESULTS"));
        if (override != null && !override.isBlank()) {
            Path path = Path.of(override);
            if (Files.exists(path)) {
                return path;
            }
        }
        Path repoRoot = detectRepoRoot();
        Path results = repoRoot.resolve("results").resolve(component).resolve("results.json");
        if (Files.exists(results) && Boolean.parseBoolean(System.getProperty("conformance.reuseResults", "false"))) {
            return results;
        }
        Path runner = repoRoot.resolve("runner").resolve("run_conformance.py");
        if (!Files.exists(runner)) {
            throw new IOException("Python runner not found at " + runner);
        }
        results.getParent().toFile().mkdirs();
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
        command.add(results.getParent().toString());

        String envEndpoint = firstNonBlank(
                System.getProperty("env.endpoint"),
                System.getenv("ENV_ENDPOINT"),
                System.getenv("CERTIFY_ISSUER_URL"));
        if (envEndpoint != null) {
            command.add("--certify-issuer-url");
            command.add(envEndpoint);
        }
        String verify = firstNonBlank(System.getProperty("verify.endpoint"), System.getenv("VERIFY_ENDPOINT"));
        if (verify != null) {
            command.add("--verify-endpoint");
            command.add(verify);
        }
        String suite = firstNonBlank(System.getProperty("conformance.server"), System.getenv("CONFORMANCE_SERVER"));
        if (suite != null) {
            command.add("--suite-url");
            command.add(suite);
        }

        ProcessBuilder builder = new ProcessBuilder(command);
        builder.directory(repoRoot.toFile());
        builder.inheritIO();
        Process process = builder.start();
        boolean finished = process.waitFor(2, TimeUnit.HOURS);
        if (!finished) {
            process.destroyForcibly();
            throw new IOException("Conformance runner timed out");
        }
        if (!Files.exists(results.getParent().resolve("results.json"))) {
            throw new IOException("Runner exited " + process.exitValue() + " without writing results.json");
        }
        return results.getParent().resolve("results.json");
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
        String configured = firstNonBlank(System.getProperty("conformance.repoRoot"), System.getenv("CONFORMANCE_REPO_ROOT"));
        if (configured != null) {
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
