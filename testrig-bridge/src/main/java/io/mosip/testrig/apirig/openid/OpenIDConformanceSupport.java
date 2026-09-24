package io.mosip.testrig.apirig.openid;

import java.nio.file.Path;
import java.util.List;

import org.testng.Assert;
import org.testng.ITestContext;
import org.testng.SkipException;
import org.testng.annotations.AfterSuite;
import org.testng.annotations.BeforeSuite;
import org.testng.annotations.DataProvider;

/**
 * Shared TestNG lifecycle used by the per-module and combined suites.
 */
public abstract class OpenIDConformanceSupport {
    private ConformanceRun run;
    private final String component;

    protected OpenIDConformanceSupport(String component) {
        this.component = component;
    }

    @BeforeSuite(alwaysRun = true)
    public void runConformance() throws Exception {
        Path results = ConformanceRunner.ensureResults(component);
        run = ResultMapper.load(results);
        System.setProperty("emailable.report2.name", "OpenIDConformance-" + component);
    }

    @DataProvider(name = "conformanceModules")
    public Object[][] conformanceModules() {
        List<ModuleResult> modules = ResultMapper.filter(run, "combined".equals(component) ? null : component);
        if (modules.isEmpty()) {
            return new Object[][] { { null } };
        }
        Object[][] data = new Object[modules.size()][1];
        for (int i = 0; i < modules.size(); i++) {
            data[i][0] = modules.get(i);
        }
        return data;
    }

    protected void assertModule(ModuleResult module) {
        if (module == null) {
            throw new SkipException("No conformance modules were returned for " + component);
        }
        if ("SKIP".equalsIgnoreCase(module.mapped) || module.expectedSkip) {
            throw new SkipException(skipReason(module));
        }
        if (module.expectedFailure && "FAIL".equalsIgnoreCase(module.mapped)) {
            throw new SkipException("Expected failure: " + skipReason(module));
        }
        Assert.assertEquals(
                module.mapped,
                "PASS",
                module.displayName() + " result=" + module.result + " status=" + module.status);
    }

    @AfterSuite(alwaysRun = true)
    public void gateBenchmark(ITestContext context) {
        BenchmarkGate.assertMet(run);
    }

    private static String skipReason(ModuleResult module) {
        if (module.reason != null && !module.reason.isBlank()) {
            return module.reason;
        }
        return module.displayName() + " mapped to " + module.mapped;
    }
}
