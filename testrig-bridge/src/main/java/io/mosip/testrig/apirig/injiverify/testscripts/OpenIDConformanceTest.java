package io.mosip.testrig.apirig.injiverify.testscripts;

import org.testng.annotations.Test;

import io.mosip.testrig.apirig.openid.ModuleResult;
import io.mosip.testrig.apirig.openid.OpenIDConformanceSupport;

/**
 * Drop-in TestNG class for the Inji Verify api-testrig.
 */
// Verify TestNG suite. One test method per verifier module in results.json.
public class OpenIDConformanceTest extends OpenIDConformanceSupport {
    public OpenIDConformanceTest() {
        super("verify");
    }

    @Test(dataProvider = "conformanceModules")
    public void openidVerifierPlan(ModuleResult module) {
        assertModule(module);
    }
}
