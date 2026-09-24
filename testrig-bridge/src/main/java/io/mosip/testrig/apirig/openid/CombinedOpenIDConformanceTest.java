package io.mosip.testrig.apirig.openid;

import org.testng.annotations.Test;

/**
 * Optional combined run: issuer + verifier plans, one report.
 */
public class CombinedOpenIDConformanceTest extends OpenIDConformanceSupport {
    public CombinedOpenIDConformanceTest() {
        super("combined");
    }

    @Test(dataProvider = "conformanceModules")
    public void openidFullStackPlan(ModuleResult module) {
        assertModule(module);
    }
}
