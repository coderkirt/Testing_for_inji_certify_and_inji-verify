# Troubleshooting

## Suite never becomes ready

- Confirm `mongodb`, `server`, and `nginx` are up: `docker compose -f compose/docker-compose.yml ps`
- Open `https://localhost.emobix.co.uk:8443/` (accept the self-signed cert)
- On Windows, add `127.0.0.1 localhost.emobix.co.uk` to `C:\Windows\System32\drivers\etc\hosts`
- The runner uses `verify=False` for the local cert. Browsers still warn.

## Plan create fails with 400

- The suite image may not yet expose the 1.0 plan name. Check `GET /api/runner/available` and update `runner/configs/plans.json`.
- Variant keys must match what that suite build supports. Start from `issuer-variant.json` / `verifier-variant.json`.

## Certify or Verify not reachable from the suite

- Plan URLs must be Docker DNS names (`http://certify-nginx`, `http://verify-service:8080/v1/verify`), not `localhost`, when the runner is driving a compose stack.
- When pointing at a deployed env (api-testrig `ENV_ENDPOINT`), set `CERTIFY_ISSUER_URL` / `VERIFY_ENDPOINT` to the public URLs the suite container can route to.

## Postgres init failed

- First boot only runs `certify_init.sql` / `verify/init.sql`. Recreate volumes: `docker compose -f compose/docker-compose.yml down -v`

## TestNG finds no modules

- `results/<mode>/results.json` is missing or the official script path was used without a mapper. Re-run without `--official-script`, or inspect the official export zip.

## Result diff

```bash
python runner/result_diff.py --previous results/previous.json --current results/combined/results.json
```

Copy a good `results.json` to `results/previous.json` to compare the next CI run.
