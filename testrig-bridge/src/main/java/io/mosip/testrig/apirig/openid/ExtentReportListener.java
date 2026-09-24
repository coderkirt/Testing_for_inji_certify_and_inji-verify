package io.mosip.testrig.apirig.openid;

import java.nio.file.Path;

import org.testng.IConfigurationListener;
import org.testng.ITestContext;
import org.testng.ITestListener;
import org.testng.ITestResult;

import com.aventstack.extentreports.ExtentReports;
import com.aventstack.extentreports.ExtentTest;
import com.aventstack.extentreports.Status;
import com.aventstack.extentreports.reporter.ExtentSparkReporter;

/**
 * Writes an Extent Spark report next to TestNG output so results can land in
 * the same automationtests bucket the api-testrig already publishes.
 */
public class ExtentReportListener implements ITestListener, IConfigurationListener {
    private ExtentReports extent;
    private final ThreadLocal<ExtentTest> current = new ThreadLocal<>();

    @Override
    public void onStart(ITestContext context) {
        String reportName = System.getProperty("emailable.report2.name", context.getName());
        Path output = Path.of("target", "extent", reportName + ".html");
        output.toFile().getParentFile().mkdirs();
        ExtentSparkReporter spark = new ExtentSparkReporter(output.toString());
        spark.config().setDocumentTitle("Inji OpenID Conformance");
        spark.config().setReportName(reportName);
        extent = new ExtentReports();
        extent.attachReporter(spark);
        extent.setSystemInfo("suite", context.getName());
        extent.setSystemInfo("env.endpoint", System.getProperty("env.endpoint", System.getenv().getOrDefault("ENV_ENDPOINT", "")));
    }

    @Override
    public void onTestStart(ITestResult result) {
        current.set(extent.createTest(result.getMethod().getMethodName() + " " + argumentLabel(result)));
    }

    @Override
    public void onTestSuccess(ITestResult result) {
        test(result).log(Status.PASS, "PASSED");
    }

    @Override
    public void onTestFailure(ITestResult result) {
        test(result).log(Status.FAIL, result.getThrowable());
    }

    @Override
    public void onTestSkipped(ITestResult result) {
        Throwable throwable = result.getThrowable();
        test(result).log(Status.SKIP, throwable == null ? "SKIPPED" : throwable.getMessage());
    }

    @Override
    public void onConfigurationFailure(ITestResult result) {
        test(result).log(Status.FAIL, result.getThrowable());
    }

    @Override
    public void onFinish(ITestContext context) {
        if (extent != null) {
            extent.flush();
        }
    }

    private ExtentTest test(ITestResult result) {
        ExtentTest existing = current.get();
        if (existing != null) {
            return existing;
        }
        ExtentTest created = extent.createTest(result.getMethod().getMethodName() + " " + argumentLabel(result));
        current.set(created);
        return created;
    }

    private static String argumentLabel(ITestResult result) {
        Object[] params = result.getParameters();
        if (params == null || params.length == 0 || params[0] == null) {
            return "";
        }
        if (params[0] instanceof ModuleResult) {
            return ((ModuleResult) params[0]).displayName();
        }
        return params[0].toString();
    }
}
