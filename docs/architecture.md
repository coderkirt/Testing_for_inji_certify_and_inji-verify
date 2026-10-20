# AutoConform Architecture Specification

AutoConform provides a unified, automated, CI-ready conformance harness for **MOSIP Inji Certify** (credential issuer) and **MOSIP Inji Verify** (verifier).

The core design principle is **strict separation of concerns**:
- **Protocol Truth**: OpenID protocol logic, cryptographic evaluations, and conformance assertions stay exclusively in the official **OpenID Foundation (OIDF) Conformance Suite**.
- **Orchestration**: The Python runner (`runner/run_conformance.py`) handles test lifecycle, configuration rendering, dynamic WAITING-handoff automation, and polling.
- **Reporting & Governance**: Conformance results map directly into MOSIP's native `io.mosip.testrig.apirig` TestNG framework and Extent Spark reporting.

---

## 1. End-to-End System Architecture

```mermaid
graph TB
    subgraph CI_Host["Host / CI Runner"]
        CLI["scripts/run-conformance.sh / .ps1"]
        Runner["Python Conformance Runner<br/>(runner/run_conformance.py)"]
        TestNG["TestNG Bridge<br/>(io.mosip.testrig.apirig)"]
        ResultsJSON[("results.json<br/>&amp; diff.json")]
        ExtentHTML["Extent Spark Report<br/>&amp; Web Dashboard"]
    end

    subgraph DockerNet["Docker Network: inji-openid-conformance"]
        subgraph OIDF_Suite["OpenID Foundation Suite v5.3.1"]
            SuiteNGINX["suite-nginx:8443<br/>(alias: localhost.emobix.co.uk)"]
            SuiteCore["suite-server (Spring Boot)"]
            MongoDB[("MongoDB")]
            SuiteNGINX --> SuiteCore
            SuiteCore --> MongoDB
        end

        subgraph Inji_Certify["Inji Certify 1.0.0-alpha.1"]
            CertifyNGINX["certify-nginx:443"]
            CertifySvc["certify-service:8080<br/>(Spring Boot)"]
            CertifyDB[("PostgreSQL")]
            CertifyNGINX --> CertifySvc
            CertifySvc --> CertifyDB
        end

        subgraph Inji_Verify["Inji Verify 0.18.2"]
            VerifySvc["verify-service:8080<br/>(Spring Boot)"]
            VerifyUI["verify-ui:80"]
            VerifyDB[("PostgreSQL")]
            VerifySvc --> VerifyDB
        end
    end

    CLI --> Runner
    Runner -- "REST API: /api/plan, /api/runner" --> SuiteNGINX
    SuiteCore -- "OpenID4VCI Requests" --> CertifyNGINX
    SuiteCore -- "OpenID4VP Direct Post" --> VerifySvc
    Runner -- "WAITING Handoff /pre-authorized-data" --> CertifyNGINX
    Runner -- "WAITING Handoff Mock VP Presentation" --> SuiteNGINX
    Runner --> ResultsJSON
    ResultsJSON --> TestNG
    TestNG --> ExtentHTML
```

---

## 2. Automated WAITING-Handoff Mechanism

Interactive OpenID4VCI and OpenID4VP test modules pause in a `WAITING` state, expecting a physical mobile wallet user to scan a QR code and present credentials. AutoConform automates this completely without human intervention.

### A. Inji Certify (Issuer) Pre-Authorized Code Handoff

```mermaid
sequenceDiagram
    autonumber
    participant Runner as AutoConform Runner
    participant Suite as OIDF Conformance Suite
    participant Certify as Inji Certify Service

    Suite->>Suite: Module begins (e.g. happy-flow)
    Suite->>Suite: State enters WAITING (waiting for wallet offer retrieval)
    Runner->>Suite: Poll GET /api/info/{testId}
    Suite-->>Runner: status = "WAITING", exposedValues: { credential_offer_uri }

    alt Pre-Authorized Code Flow
        Runner->>Certify: POST /pre-authorized-data<br/>{ claims: { sub: "F001" }, tx_code: "1234" }
        Certify-->>Runner: HTTP 200 { pre-authorized_code, tx_code: "1234" }
        Runner->>Suite: Resolve credential-offer-by-value & deliver to suite
    end

    Suite->>Certify: POST /token (grant_type=pre_auth_code, DPoP proof)
    Certify-->>Suite: HTTP 200 { access_token, c_nonce }
    Suite->>Certify: POST /credential (FarmerCredential SD-JWT)
    Certify-->>Suite: HTTP 200 { credential, notification_id }
    Suite->>Suite: Validates SD-JWT VC format & key binding
    Suite->>Suite: State enters FINISHED (PASSED)
```

### B. Inji Verify (Verifier) Mock Presentation Handoff

```mermaid
sequenceDiagram
    autonumber
    participant Runner as AutoConform Runner
    participant Suite as OIDF Conformance Suite
    participant Verify as Inji Verify Service

    Runner->>Verify: POST /v1/verify/vp-request<br/>{ presentation_definition: SD_JWT_PRESENTATION_DEFINITION }
    Verify-->>Runner: HTTP 200 { request_uri, client_id, state }
    
    Runner->>Suite: Hand off authorization request URL to Suite Mock Wallet
    Suite->>Verify: GET {request_uri} (Fetches signed presentation request)
    Verify-->>Suite: HTTP 200 (presentation_definition)
    
    Suite->>Suite: Generates Mock SD-JWT VC + Key-Binding JWT
    Suite->>Verify: POST /v1/verify/direct_post<br/>{ vp_token, state, presentation_submission }
    Verify-->>Suite: HTTP 200 { status: "SUCCESS" }
    
    Suite->>Suite: State enters FINISHED (PASSED or mapped against expected failure)
```

---

## 3. Results Governance & Benchmark Gate

Test outcomes are classified and mapped into TestNG results via `ResultMapper.java` and `BenchmarkGate.java`:

```mermaid
flowchart TD
    Raw[Raw Suite Module Status] --> CheckStatus{Status?}
    CheckStatus -- "FINISHED & PASSED" --> Pass[Map: PASS]
    CheckStatus -- "SKIPPED / NOT_RUN" --> ExpSkip{Listed in expected-skips?}
    ExpSkip -- Yes --> Skip1[Map: SKIP<br/>Annotated with reason]
    ExpSkip -- No --> UnexpSkip[Unexpected Skip]
    
    CheckStatus -- "FAILED / INTERRUPTED" --> ExpFail{Listed in expected-failures?}
    ExpFail -- "Yes (Documented Product Gap)" --> Skip2[Map: SKIP<br/>Expected Failure: e.g. HAIP 1.0 Final vs Draft 21]
    ExpFail -- "No (Regressive Failure)" --> Fail[Map: FAIL<br/>Unexpected Failure]

    Pass --> Gate[BenchmarkGate]
    Skip1 --> Gate
    Skip2 --> Gate
    UnexpSkip --> Gate
    Fail --> Gate

    Gate --> CheckGate{"minPassRate &ge; 50% &amp;&amp;<br/>unexpectedFailures == 0 &amp;&amp;<br/>all required modules ran?"}
    CheckGate -- Yes --> BuildPass[Exit 0: Build Passed]
    CheckGate -- No --> BuildFail[Exit 1: Build Failed]
```

---

## 4. CI/CD GitHub Actions Pipeline

```mermaid
flowchart LR
    Push[git push / PR] --> Setup[Setup Python & Java]
    Setup --> DockerBoot["docker compose up -d<br/>(OIDF + Certify + Verify)"]
    DockerBoot --> Health["Wait for /ready &amp; /healthcheck"]
    Health --> RunHarness["python runner/run_conformance.py --combined"]
    RunHarness --> GenResults["results/results.json &amp; diff.json"]
    GenResults --> TestNGBridge["mvn test -Dconformance.reuseResults=true"]
    TestNGBridge --> ExtentReport["Generate Extent Spark HTML"]
    ExtentReport --> Upload["Upload Artifacts &amp; Publish Dashboard"]
```

---

## 5. Network & Security Architecture

1. **Shared Network (`inji-openid-conformance`)**:
   All 7 containers operate on an isolated bridge network with service discovery.
2. **Suite Host Alias (`localhost.emobix.co.uk`)**:
   The suite issues self-signed TLS certificates for `localhost.emobix.co.uk`. Inji Certify and Verify resolve this alias directly over Docker's internal DNS to satisfy OpenID `redirect_uri` and callback host matching.
3. **Transport Security & DPoP Binding**:
   - Inji Certify is reverse-proxied through NGINX with SSL termination on port 443.
   - RFC 9449 Demonstrating Proof-of-Possession (DPoP) is enforced on all token and credential requests.
4. **Endpoint Aliases**:
   - Certify Issuer: `https://certify-nginx`
   - Verify Service: `http://verify-service:8080/v1/verify`
   - Suite NGINX: `https://localhost.emobix.co.uk:8443`
