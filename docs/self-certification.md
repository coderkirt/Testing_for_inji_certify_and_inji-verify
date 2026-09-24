# Submitting for OpenID self-certification

Local Docker runs are for CI gates. Official self-certification uses the OpenID Foundation process:

1. Confirm Inji Certify / Inji Verify target **OpenID4VCI 1.0** and **OpenID4VP 1.0** (HAIP where required).
2. Run the same plan names and variants this harness commits (`runner/configs/*`).
3. Export the suite HTML/JSON package (`results/<mode>/*.zip` from `exporthtml`).
4. Follow [How to Certify Your Implementation](https://openid.net/certification/how-to-certify-your-implementation/).
5. Use the hosted certification environment when a signed package is required. The local suite (`dev` profile, no token) is not a substitute for a paid certification submission.

Keep `expected-failures.json` empty for a certification candidate. Known issues belong in a waiver, not a silent skip.
