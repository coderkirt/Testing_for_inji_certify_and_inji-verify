package io.mosip.testrig.apirig.openid;

public class ModuleResult {
    public String component;
    public String planName;
    public String planId;
    public String testModule;
    public String testId;
    public String status;
    public String result;
    public String mapped;
    public boolean expectedFailure;
    public boolean expectedSkip;
    public String reason;

    public String displayName() {
        return (component == null ? "" : component + " / ") + testModule;
    }
}
