# MOSIP Decode 2026 — Pitch Deck Content
### Project: AutoConform — Automated OpenID Conformance Testing for Inji Certify & Inji Verify

Prepared from a full analysis of the repository `Testing_for_inji_certify_and_inji-verify-main`
(every slide below maps to the MOSIP Decode 2026 Submission Guidelines PDF).

---

## SLIDE 1 — Title Slide

**AutoConform**
### One-Command OpenID Conformance Testing for MOSIP Inji Certify & Inji Verify

- Automated, CI-ready conformance harness for **OpenID4VCI 1.0** (issuer) and **OpenID4VP / HAIP 1.0** (verifier)
- Built on the official **OpenID Foundation Conformance Suite** — zero re-invented protocol logic
- Team Name · Member Names · College/University · Track: Digital Credential Trust Infrastructure

> 🎤 *Speaker notes:* "We automated the most painful, manual part of digital-credential compliance: proving that MOSIP's issuer and verifier actually speak OpenID4VCI and OpenID4VP correctly — with a single command, in CI, with MOSIP's own TestNG reporting."

---

## SLIDE 2 — The Problem

**Conformance testing today is manual, slow, and invisible to CI**

- The OpenID Foundation conformance suite is a powerful but **UI-driven** tool: plans are created by clicking, variants are selected by hand, and results live in a web dashboard
- Interactive OpenID4VP modules **stall in WAITING** until a wallet completes a presentation — a human must paste links
- Inji Certify (credential issuer) and Inji Verify (verifier) release frequently, but **nothing re-checks standards compliance automatically** on every change
- Results never reach the reporting pipeline MOSIP teams already use (api-testrig → TestNG → Extent)
- Consequence: **spec drift is discovered late** — e.g., draft-spec fields still being sent against 1.0 endpoints — only when someone manually clicks through the suite

> 🎤 *Speaker notes:* Emphasize the gap between "the suite exists" and "the suite runs on every commit." Judges from MOSIP will recognize api-testrig and the pain of keeping Inji modules release-ready.

---

## SLIDE 3 — Why It Matters (Impact of the Problem)

- **Trust:** Verifiable credentials only work if every issuer and verifier implements the spec identically — one non-conformant field breaks interoperability across the whole ecosystem
- **Cost:** A single manual conformance sweep takes hours of expert time per release; regressions found late are the most expensive kind
- **Certification readiness:** OpenID self-certification/certification requires exact plan + variant runs and exported evidence packages — today assembled by hand
- **Ecosystem scale:** MOSIP-based ID systems serve 500M+ people; wallet ecosystems built on Inji depend on issuer ↔ verifier interoperability

> 🎤 *Speaker notes:* Frame it as "compliance as code" — the same shift CI brought to unit testing, applied to standards conformance.

---

## SLIDE 4 — Our Solution (Overview)

**AutoConform = Docker stack + REST-driven runner + TestNG bridge, wired into CI**

- 🐳 **Full-stack compose:** official OIDF conformance suite + Inji Certify 0.14 + Inji Verify 0.18.2 on one Docker network — `docker compose up -d` brings up 7 services
- ⚙️ **Orchestration-only runner (Python):** drives the suite REST API exactly like the official `run-test-plan.py` — create plan → run module → poll → export — but fully unattended
- 🤝 **Automated WAITING handoff:** when the suite waits for a wallet, the runner *acts as the wallet*: it delivers credential offers to Certify and hands VP authorization requests to the suite's fake wallet
- 📊 **MOSIP-native reporting:** every suite module becomes a TestNG test → Extent Spark report → benchmark gate that fails the build on regressions
- 🚦 **One command:** `./scripts/run-conformance.sh --combined` (bash) or `.\scripts\run-conformance.ps1 -Combined` (Windows)

> 🎤 *Speaker notes:* Key principle to say out loud: **"We implement no OpenID protocol tests ourselves."** All protocol logic stays in the official suite; we orchestrate, map, and gate. That keeps the harness trustworthy forever.

---

## SLIDE 5 — What We Demo (Working Prototype)

**Live end-to-end run, ~4 minutes:**

1. `run-conformance.sh --component certify` → compose pulls up the stack, suite becomes healthy
2. Runner creates the **`oid4vci-1_0-issuer-test-plan`** via REST; modules start executing
3. **The wow moment:** a module hits `WAITING` → runner calls Certify's `pre-authorized-data` API with farmer identity claims → fetches the credential offer → delivers it to the suite → module resumes and **PASSES without a human**
4. Same for Verify: runner creates a VP request, rewrites it to the suite's `authorize` endpoint, and hands it to the fake wallet
5. Console prints the summary JSON; **Extent Spark report** opens with per-module results; benchmark gate evaluation
6. Flip to GitHub Actions: the same run green on CI, artifacts (results.json + HTML export zips) uploaded

> 🎤 *Speaker notes:* Record this exact script for the 2–5 min Video Demo deliverable. Screen-record the Extent report — it's the visual proof that maps to MOSIP's reporting standards.

---

## SLIDE 6 — System Architecture

*(Insert diagram — see sketch below)*

```
 run-conformance.sh / run-conformance.ps1          ← one command
        │
        ├── docker compose (inji-openid-conformance network)
        │      ├── OIDF suite: mongodb + server + nginx :8443  (alias: localhost.emobix.co.uk)
        │      ├── Inji Certify: certify + certify-nginx + postgres 15
        │      └── Inji Verify: verify-service + verify-ui + postgres 13
        │
        ├── runner/run_conformance.py  (orchestration engine)
        │      ├── oidf_client.py      REST: POST /api/plan → POST /api/runner
        │      │                       poll GET /api/info → GET /api/plan/exporthtml
        │      ├── config_render.py    renders ${CERTIFY_ISSUER_URL} / ${VERIFY_ENDPOINT}
        │      ├── WAITING handoffs    credential offer (Certify) · VP authz request (Verify)
        │      └── results.json + HTML export zip
        │
        └── testrig-bridge (Java/TestNG)
               ├── OpenIDConformanceTest  1 TestNG test per suite module
               ├── ResultMapper           PASS / FAIL / SKIP (+expected)
               ├── BenchmarkGate          fails suite on unexpected failures
               └── Extent Spark report
```

- **Three clean layers:** Infrastructure (compose) · Orchestration (Python) · Reporting (Java/TestNG)
- Network aliasing trick: suite nginx is aliased `localhost.emobix.co.uk` so advertised BASE_URL callbacks just work; plans use Docker DNS names (`http://certify-nginx`) because *the suite container*, not the host, calls the implementations

> 🎤 *Speaker notes:* Point out the deliberate boundaries: "orchestration only" — protocol logic in the OIDF suite, reporting in MOSIP api-testrig conventions. This is what makes it a drop-in, not a fork.

---

## SLIDE 7 — Technology Stack

| Layer | Technology | Why |
|---|---|---|
| Orchestration engine | **Python 3.10+ / httpx** (826 LOC) | Thin, auditable REST wrapper; official-script parity |
| Reporting bridge | **Java 11 + Maven, TestNG + Extent** (505 LOC) | Same reports MOSIP api-testrig already publishes |
| Infrastructure | **Docker Compose** — 7 services, pinned images (Certify 0.14.0, Verify 0.18.2, Mongo 6.0.13, Postgres 15/13, nginx) | Fully reproducible, zero local installs |
| Suite | **OpenID Foundation Conformance Suite** (prebuilt image) | The authoritative source of protocol truth |
| Entry points | Bash + PowerShell (328 LOC) | `--component certify/verify`, `--combined`, `--parallel` |
| CI | **GitHub Actions** (full-stack-conformance.yml) | Compose up → conformance → TestNG → artifact upload, 120-min budget |
| Config as data | JSON plans/variants (9 issuer + 2 verifier variants) | Edit JSON, never click the suite UI |

> 🎤 *Speaker notes:* Stress reproducibility: pinned image tags, healthchecks with start periods on every service, and committed plan templates — anyone can re-run the exact same evaluation.

---

## SLIDE 8 — Key Feature 1: The Orchestration Engine

**Everything the official script does — unattended, in parallel, in CI**

- Mirrors the documented REST flow: wait `GET /api/plan?length=1` ready → `POST /api/plan` → `GET /api/plan/{id}` → `POST /api/runner` per module → poll `GET /api/info/{testId}` → `exporthtml` package
- **`--parallel`:** Certify and Verify plans run concurrently (2 threads) and suite modules run concurrently (capped at 4) — cuts wall-clock time dramatically
- Renders committed 1.0 plan templates with environment endpoints, so the same repo targets **local Docker or a deployed environment** (`ENV_ENDPOINT` — same contract as api-testrig)
- Optional escape hatch: `--official-script` delegates to OIDF's `run-test-plan.py` when a byte-for-byte official run is required
- Dual mapping discipline: results classified PASS / FAIL / SKIP with **per-module provenance** (testId, raw status, expected flag, reason)

> 🎤 *Speaker notes:* "Deterministic variant selection from JSON" matters — wrong variants clicked in the UI masquerade as product bugs. We made that class of mistake impossible.

---

## SLIDE 9 — Key Feature 2: Automated WAITING Handoff (the Innovation)

**The runner becomes the wallet. No human in the loop.**

- **Issuer side:** on `WAITING`, the runner POSTs farmer claims (id, fullName, mobile, DOB, gender, farmerID) + tx_code to Certify's `/pre-authorized-data`, resolves the credential-offer URI, fetches the offer JSON, and delivers it **by value** to the suite's offer endpoint (suite 5.31 rejects `http://` offer URIs — we worked around it)
- **Verifier side:** runner creates a Verify `vp-request` with an SD-JWT presentation definition (DCQL constraints on `vct`), rewrites the request to the suite's `authorize` endpoint, and completes the presentation against the fake wallet
- Host-aware URL rewriting (`_host_reachable_url`, `_suite_host_url`) bridges Docker DNS ↔ host-reachable addresses automatically
- Interactive modules that genuinely can't run unattended are **explicitly skipped via config**, never silently green

> 🎤 *Speaker notes:* This is the single hardest problem in OpenID4VP testing — everyone demos this with a human holding a phone. Automating the handshake is what makes CI conformance possible at all. Lead with this slide if short on time.

---

## SLIDE 10 — Key Feature 3: Honest Results Governance

**Known gaps become data, not noise**

- **`expected-failures.json`:** 18 documented module failures, each with the *root cause* as a comment — e.g. *"Certify 0.14 rejects `credential_configuration_id` on /issuance/credential (sends draft-13 `format`/`vct` fields)"*, *"Verify 0.18.2 is OpenID4VP draft 21 (DID + direct_post), not HAIP 1.0 Final (x509_hash + request_uri_signed + direct_post.jwt)"*
- Expected failures surface as **TestNG skips with reasons** — visible, never silently green
- **`benchmark.json` gate:** fails the build on unexpected failures, optional minimum pass rate, required-module list, unexpected-skip detection
- **`result_diff.py`:** compare any run against a baseline — instantly see new failures/new passes after a product upgrade
- Certification discipline: expected-failures must be **empty** for a certification candidate; known issues belong in waivers

> 🎤 *Speaker notes:* We found and precisely documented two real spec-drift gaps in the current Inji images. That's the harness already paying for itself — it converts "the test failed" into "here is exactly which spec clause diverges."

---

## SLIDE 11 — MOSIP api-testrig Integration

**A drop-in for the pipeline MOSIP already runs**

- Bridge classes live under `io.mosip.testrig.apirig.openid` — same namespace and conventions as api-testrig
- `OpenIDConformanceTest` reads `results.json` (or **launches the Python runner itself** using the existing `env.endpoint`) — so testrig suites gain conformance checks without new infrastructure
- One TestNG suite per module (`testng-certify.xml`, `testng-verify.xml`) + optional `CombinedOpenIDConformanceTest` cross-module badge
- Independent gates per component; combined run only adds the summary badge — a Verify skip never blocks the Certify gate
- Java `ConformanceRunner` handles repo discovery, Python executable resolution, 2-hour timeout, and env/property passthrough

> 🎤 *Speaker notes:* This answers "why not just write more tests?" — because it plugs conformance into the exact reporting MOSIP teams review every day. Adoption friction ≈ zero.

---

## SLIDE 12 — Standards & Compliance Coverage

| Target | Plan executed | Profile details |
|---|---|---|
| **Inji Certify — issuer** | `oid4vci-1_0-issuer-test-plan` | SD-JWT VC format, `private_key_jwt` client auth, DPoP sender constraint, pre-authorized-code grant, issuer-initiated variants |
| **Inji Verify — verifier** | `oid4vp-1final-verifier-haip-test-plan` | SD-JWT VC, `direct_post.jwt`, DCQL claim constraints, trust-anchor PEM pinned in config |
| Self-certification path | Same committed plan names/variants + `exporthtml` package | Ready for OpenID's "How to Certify Your Implementation" process; hosted environment used for signed submissions |

- 9 issuer variants + 2 verifier variants committed as JSON — the exact matrix for official certification runs
- Full stack on one bridge network with suite-advertised callback URLs — the configuration certification auditors expect

> 🎤 *Speaker notes:* MOSIP Decode judges care about standards alignment — this slide says the project *is* the standards-alignment tooling.

---

## SLIDE 13 — Test Cases & Results (Evidence)

- **Per-module conformance evidence:** every OIDF module gets testId, raw suite status, mapped result, expected/reason metadata in `results.json`
- **Two-layer reporting:** suite's own HTML export zip (official evidence for self-certification) + Extent Spark report (MOSIP-native view)
- **Trend management:** `result_diff.py` against `results/previous.json` → new/regressed/fixed modules per run; CI artifacts uploaded on every push and PR
- **Edge cases covered by the suite itself:** negative-path modules (invalid KB-JWT signature/nonce/aud, iat in past/future, invalid SD hash, invalid credential signature, unknown credential configuration/identifier, access token in query, missing proofs…) — all orchestrated unattended where feasible
- **Test data shipped:** `farmer_identity_data.csv`, pre-authorized tx_code `1234`, FarmerCredential configuration, DCQL presentation definitions — all in-repo

> 🎤 *Speaker notes:* For the "Test Cases and Results" deliverable: attach a sample `results.json` + Extent report screenshot + a `diff.json`. The benchmark gate output (`benchmarkMet`, reasons) is itself a test-case summary a jury can read in 10 seconds.

---

## SLIDE 14 — Installation & Evaluation Guide (for the Jury)

```bash
# 1. Prerequisites: Docker Desktop, Python 3.10+, Java 11 + Maven
# 2. Hosts entry (required once)
#    Windows: C:\Windows\System32\drivers\etc\hosts
#    Linux/macOS: /etc/hosts
127.0.0.1 localhost.emobix.co.uk

# 3. One command
git clone <repo-url> && cd <repo>
cp compose/.env.example compose/.env
./scripts/run-conformance.sh --component certify   # or --combined

# Windows: .\scripts\run-conformance.ps1 -Component certify
```

- What you'll see: compose healthchecks → suite ready → module-by-module progress → summary JSON → Extent report → exit code reflects the benchmark gate
- Point at an existing environment instead of local Docker: `export ENV_ENDPOINT=… VERIFY_ENDPOINT=…` + `--skip-compose`
- Compare two runs: `python runner/result_diff.py --previous results/previous.json --current results/combined/results.json`
- Docs included: architecture, API automation, per-component handoff, self-certification, troubleshooting (286 lines across 7 docs)

> 🎤 *Speaker notes:* README + docs + troubleshooting satisfy the "Usage and Installation Instructions" and "API Documentation" guidelines — jury members can evaluate independently, including on Windows.

---

## SLIDE 15 — Impact & Roadmap

**Impact now**
- Hours of expert manual testing → **one command in CI**, on every push and PR
- Spec drift caught at commit time, with **root-cause comments**, not mystery failures
- Certification evidence (HTML packages + exact variant matrix) generated automatically
- MOSIP teams keep their existing TestNG/Extent workflow — zero retraining

**Next**
1. **Wallet stub service** to automate the remaining interactive OpenID4VP modules (remove the last skips)
2. **Certify 1.0 field upgrade** — flip 7 expected failures to real passes when `credential_configuration_id` support lands
3. **HAIP 1.0 Final profile support** in the Verify pipeline (`request_uri_signed`, `x509_hash`)
4. **Trend dashboard** — pass-rate history per release across `result_diff.json` artifacts
5. **OpenID official certification submission** for both components using the hosted environment

> 🎤 *Speaker notes:* Roadmap items 2 and 3 are direct payoff slides — the harness already tells MOSIP exactly what to fix to reach full 1.0 conformance.

---

## SLIDE 16 — Closing

**AutoConform — conformance as code for the Inji credential ecosystem**

- 🔗 Repository: `<github.com/your-team/autoconform>` *(host on GitHub/GitLab with full commit history — see checklist)*
- 🎬 Demo video: `<link>` (2–5 min, script = Slide 5)
- 🧪 Evidence pack: `results.json` · Extent report · suite HTML exports · `diff.json`
- Thank you — Questions?

---

---

# APPENDIX A — Submission Checklist Mapping (from the MOSIP Decode 2026 guidelines PDF)

| Guideline requirement | Where it's satisfied | Status |
|---|---|---|
| **Source Code** *(mandatory)* — well-organised, commented, hosted on GitHub/GitLab/Bitbucket, all files to run | This repo: layered structure (compose / runner / testrig-bridge / scripts / docs), docstrings + Javadoc throughout, ~2.5k LOC | ✅ Push to GitHub with full history |
| **Working Prototype or Demo** *(mandatory)* — functional, demonstrates core features | One-command harness; live demo script in Slide 5 | ✅ |
| **Pitch Presentation / Slide Deck** *(mandatory)* — problem, solution, tech stack, target audience, impact | This document, Slides 1–16 | ✅ |
| **Video Demo** — 2–5 min, live/screen-recorded | Record per Slide 5 storyboard | ⬜ Record & upload |
| **Design Mockups / Wireframes** — UI/UX visuals, user-flow diagrams | Add a Figma/sketch of: (a) the CI pipeline flow, (b) WAITING-handoff sequence diagram, (c) Extent report screenshot as the "product UI" | ⬜ Create simple diagrams |
| **Architecture Diagram** — components, data flow, interactions | Slide 6 (render as image); docs/architecture.md | ✅ Render to PNG |
| **Test Data** — accounts, credentials, samples | `farmer_identity_data.csv`, tx_code `1234`, `FarmerCredential`, DCQL definitions, `.env.example`, verifier trust-anchor PEM | ✅ In-repo; list on one slide |
| **Test Cases and Results** | `results.json` (per-module with reasons), Extent report, `diff.json`, benchmark gate output, expected-failures/skips with root causes | ✅ Attach artifacts |
| **Usage & Installation Instructions** *(mandatory)* | README quick-start + Slide 14 + troubleshooting guide (Windows + Linux) | ✅ |
| **API Documentation** *(if applicable)* | Docs of both consumed APIs: OIDF suite REST endpoints (`/api/plan`, `/api/runner`, `/api/info`, `exporthtml`) in docs/api-automation.md; Certify `pre-authorized-data`; Verify `vp-request` — endpoint, request/response formats, examples | ✅ Could add an OpenAPI-style page for polish |
| **Git Repository with Version Control History** *(mandatory)* | Ensure the GitHub repo retains feature-branch history showing team collaboration | ⬜ Verify history is pushed |
| **College/University Credentials** *(mandatory)* | Each member uploads valid student ID | ⬜ Team action |

**Target audience (per guidelines):** MOSIP platform team, Inji module maintainers, OpenID Foundation certification community, and any government deploying wallet-based credential ecosystems.

---

# APPENDIX B — Suggested Design Tips for the Deck

- **10–20-10 rule:** ≤16 slides, one message per slide, ≤6 bullets per slide
- Use the architecture diagram (Slide 6) as the *centerpiece* — judges reward systems thinking
- Show a real Extent report screenshot and a real `results.json` summary — concrete evidence beats claims
- Color-code the standards: OpenID4VCI (issuer/blue), OpenID4VP (verifier/green)
- Put the 18 expected failures chart (7 Certify / 11 Verify) as a small donut on Slide 10 — "documented reality" reads as engineering maturity
- Rehearse to **5 minutes**: Slides 1–4 (2 min), 5 demo (1.5 min), 6–12 (1.5 min), 15 close (0.5 min)
