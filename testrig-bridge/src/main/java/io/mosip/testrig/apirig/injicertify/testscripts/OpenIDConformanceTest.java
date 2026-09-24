package io.mosip.testrig.apirig.injicertify.testscripts;

import org.testng.annotations.Test;

import io.mosip.testrig.apirig.openid.ModuleResult;
import io.mosip.testrig.apirig.openid.OpenIDConformanceSupport;

/**
 * Drop-in TestNG class for the Inji Certify api-testrig.
 * Copy this class (and the shared openid package) into mosip-functional-tests.
 */
public class OpenIDConformanceTest extends OpenIDConformanceSupport {
    public OpenIDConformanceTest() {
        super("certify");
    }

    @Test(dataProvider = "conformanceModules")
    public void openidIssuerPlan(ModuleResult module) {
        assertModule(module);
    }
}
