package io.mosip.testrig.apirig.openid;

import org.testng.annotations.Test;

/**
 * Optional combined run: issuer + verifier plans, one report.
 */
// TestNG entry for a combined Certify and Verify results file.
public class CombinedOpenIDConformanceTest extends OpenIDConformanceSupport {
    public CombinedOpenIDConformanceTest() {
        super("combined");
    }

    @Test(dataProvider = "conformanceModules")
    public void openidFullStackPlan(ModuleResult module) {
        assertModule(module);
    }
}
