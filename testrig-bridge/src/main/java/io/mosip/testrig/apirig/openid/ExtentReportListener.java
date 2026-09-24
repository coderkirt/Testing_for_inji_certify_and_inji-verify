package io.mosip.testrig.apirig.openid;

import java.nio.file.Path;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

import org.testng.IConfigurationListener;
import org.testng.ITestContext;
import org.testng.ITestListener;
import org.testng.ITestResult;

import com.aventstack.extentreports.ExtentReports;
import com.aventstack.extentreports.ExtentTest;
import com.aventstack.extentreports.Status;
import com.aventstack.extentreports.reporter.ExtentSparkReporter;

/**
 * Writes an Extent Spark report next to the TestNG output so conformance
 * results land in the same place the api-testrig already publishes.
 *
 * Each module becomes one test node carrying the condition level evidence, so
 * a reader can tell a clean pass from a module that only passed because its
 * failures were declared acceptable.
 *
 * IConfigurationListener is implemented as well as ITestListener because the
 * conformance run happens in @BeforeSuite: if it throws, that is a
 * *configuration* failure and ITestListener alone would never be told about it,
 * leaving an empty Extent report for what is actually the most important
 * failure in the suite.
 *
 * One ExtentReports instance is shared per report name, because onStart is
 * called once per <test> element, not once per suite. Building a fresh reporter
 * in each of them would point every flush at the same file and the last test
 * would overwrite the consolidated report - which is exactly what a suite that
 * runs the mapper unit tests and then the modules must not do.
 */
public class ExtentReportListener implements ITestListener, IConfigurationListener {
    private static final Map<String, ExtentReports> REPORTS = new ConcurrentHashMap<>();

    private ExtentReports extent;
    private final ThreadLocal<ExtentTest> current = new ThreadLocal<>();

    @Override
    public void onStart(ITestContext context) {
        String reportName = System.getProperty("emailable.report2.name", context.getName());
        Path output = Path.of("target", "extent", reportName + ".html");
        extent = REPORTS.computeIfAbsent(reportName, name -> createReport(name, output));
        extent.setSystemInfo("suite", context.getName());
        extent.setSystemInfo("env.endpoint",
                System.getProperty("env.endpoint", System.getenv().getOrDefault("ENV_ENDPOINT", "")));
        extent.setSystemInfo("conformance.report", output.toString());
    }

    private static ExtentReports createReport(String reportName, Path output) {
        Path parent = output.getParent();
        if (parent != null) {
            parent.toFile().mkdirs();
        }
        ExtentSparkReporter spark = new ExtentSparkReporter(output.toString());
        spark.config().setDocumentTitle("Inji OpenID Conformance");
        spark.config().setReportName(reportName);
        ExtentReports reports = new ExtentReports();
        reports.attachReporter(spark);
        reports.setSystemInfo("suite", reportName);
        return reports;
    }

    @Override
    public void onTestStart(ITestResult result) {
        ExtentTest test = createTest(result.getMethod().getMethodName() + " " + argumentLabel(result));
        ModuleResult module = moduleOf(result);
        if (module != null) {
            if (module.outcome != null) {
                test.info("suite status: " + module.status + " / result: " + module.result
                        + " (outcome " + module.outcome + ")");
            }
            if (module.configFile != null) {
                test.info("plan: " + module.planName + " (" + module.configFile + ")");
            }
        }
        current.set(test);
    }

    @Override
    public void onTestSuccess(ITestResult result) {
        ExtentTest test = test(result);
        if (test == null) {
            return;
        }
        ModuleResult module = moduleOf(result);
        if (module != null && module.hasConditionData()) {
            test.info(module.conditionSummary());
        }
        test.log(Status.PASS, "PASSED");
    }

    @Override
    public void onTestFailure(ITestResult result) {
        ExtentTest test = test(result);
        if (test == null) {
            return;
        }
        ModuleResult module = moduleOf(result);
        if (module != null && !module.evidenceSummary().isBlank()) {
            test.info(module.evidenceSummary().replace("\n", "<br>"));
        }
        test.log(Status.FAIL, result.getThrowable());
    }

    @Override
    public void onTestSkipped(ITestResult result) {
        ExtentTest test = test(result);
        if (test == null) {
            return;
        }
        Throwable throwable = result.getThrowable();
        ModuleResult module = moduleOf(result);
        String reason = throwable == null
                ? (module == null ? "SKIPPED" : module.reasonOr("SKIPPED"))
                : throwable.getMessage();
        if (module != null && module.hasConditionData()) {
            test.info(module.conditionSummary());
        }
        test.log(Status.SKIP, reason == null ? "SKIPPED" : reason);
    }

    @Override
    public void onConfigurationSuccess(ITestResult result) {
        // Nothing to report: setup steps are not test results.
    }

    @Override
    public void onConfigurationFailure(ITestResult result) {
        ExtentTest test = test(result);
        if (test == null) {
            return;
        }
        test.log(Status.FAIL, "Setup failed: " + describe(result));
    }

    @Override
    public void onConfigurationSkip(ITestResult result) {
        ExtentTest test = test(result);
        if (test != null) {
            test.log(Status.SKIP, "Setup skipped: " + describe(result));
        }
    }

    private static String describe(ITestResult result) {
        Throwable throwable = result.getThrowable();
        if (throwable == null) {
            return result.getMethod().getMethodName();
        }
        return result.getMethod().getMethodName() + " - " + throwable;
    }

    @Override
    public void onFinish(ITestContext context) {
        if (extent != null) {
            // Shared across test elements, so serialise the flush; the file is
            // rewritten with the accumulated nodes each time.
            synchronized (extent) {
                extent.flush();
            }
        }
        current.remove();
    }

    private ExtentTest createTest(String name) {
        synchronized (extent) {
            return extent.createTest(name);
        }
    }

    private ExtentTest test(ITestResult result) {
        if (extent == null) {
            // A configuration failure can be reported before onStart ran.
            return null;
        }
        ExtentTest existing = current.get();
        if (existing != null) {
            return existing;
        }
        ExtentTest created = createTest(
                result.getMethod().getMethodName() + " " + argumentLabel(result));
        current.set(created);
        return created;
    }

    private static ModuleResult moduleOf(ITestResult result) {
        Object[] params = result.getParameters();
        if (params == null || params.length == 0 || !(params[0] instanceof ModuleResult)) {
            return null;
        }
        return (ModuleResult) params[0];
    }

    private static String argumentLabel(ITestResult result) {
        ModuleResult module = moduleOf(result);
        if (module != null) {
            return module.displayName();
        }
        Object[] params = result.getParameters();
        if (params == null || params.length == 0 || params[0] == null) {
            return "";
        }
        return params[0].toString();
    }
}
