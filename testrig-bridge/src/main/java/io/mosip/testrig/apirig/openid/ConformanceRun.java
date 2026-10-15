package io.mosip.testrig.apirig.openid;

import java.util.Collections;
import java.util.List;

// One runner invocation: mode, timestamps, and the module list.
public class ConformanceRun {
    public String mode;
    public boolean benchmarkMet = true;
    public List<String> benchmarkReasons = Collections.emptyList();
    public int passed;
    public int failed;
    public int skipped;
    public int unexpectedFailures;
    public List<ModuleResult> modules = Collections.emptyList();
}
