# Compose stack

Brings up the OpenID Foundation prebuilt suite plus Inji Certify and Inji Verify on one Docker network.

```bash
cp compose/.env.example compose/.env
docker compose --env-file compose/.env -f compose/docker-compose.yml up -d
```

## Hosts file

The suite advertises `https://localhost.emobix.co.uk:8443`. Add:

```
127.0.0.1 localhost.emobix.co.uk
```

to `/etc/hosts` or `C:\Windows\System32\drivers\etc\hosts`.

## Selective start

```bash
docker compose -f compose/docker-compose.yml up -d mongodb server nginx
docker compose -f compose/docker-compose.yml up -d mongodb server nginx certify-db certify certify-nginx
docker compose -f compose/docker-compose.yml up -d mongodb server nginx verify-db verify-service verify-ui
```

Image tags are pinned in `.env.example` and can be overridden for 1.0.x releases.
