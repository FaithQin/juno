# Walkthrough 3: running juno somewhere that never sleeps

Until now juno was a process in a terminal tab: close the lid and it stops. This phase
moves it to a small Linux server (a DigitalOcean droplet) where it runs around the clock,
restarts itself if it crashes, and survives reboots.

## Why Docker

juno needs Python 3.13, `uv`, and its dependencies. You could install all of that on the
server by hand, but then moving to another host (you plan to, when you outgrow the $6
droplet) means doing it all again. A Docker image is that whole environment in one file;
`docker compose up` builds and runs it identically anywhere.

`Dockerfile` builds the image in two layers: dependencies first, code second, so a code-only
change rebuilds in seconds. `docker-compose.yml` says how to run it: restart automatically,
read secrets from `.env`, and mount four files from the server's disk into the container:

- `data/` — the SQLite database and the Google token. This is juno's memory; it lives on the
  server, not in the image.
- `persona.md`, `assistant.yaml`, `courses.yaml` — mounted read-only so you can edit them
  on the server and restart without rebuilding.

## The two scripts

`scripts/server-setup.sh` runs once, on the server, as root: installs Docker, opens the
firewall for SSH only, creates `/opt/juno`. Nothing else needs to be open: Telegram is
polled outbound, and the calendar, Todoist, Canvas and OpenAI are all outbound too.

`scripts/deploy.sh root@IP` runs from your Mac, every time you change something. It rsyncs
the project (including `.env`, which never goes through GitHub) and rebuilds the container.
It copies `data/` only on the first deploy; after that the server's database is the truth
and a stale laptop copy must never overwrite it.

## The one-instance rule

Telegram allows one poller per bot token. If juno runs on the Mac and the server at the
same time, they fight over messages and both log conflict errors. Before the first deploy,
stop the Mac instance (Ctrl-C in its tab). From then on, `uv run assistant run` on the Mac
is only for development, and only while the server copy is stopped.

## Day to day

```bash
scripts/deploy.sh root@IP                        # ship a change
ssh root@IP 'cd /opt/juno && docker compose logs -f juno'   # watch it
ssh root@IP 'cd /opt/juno && docker compose restart juno'   # after editing assistant.yaml
ssh root@IP 'cd /opt/juno && docker compose down'           # stop it
```

Secrets stay in two places only: your Mac's `.env` and the server's `/opt/juno/.env`,
both readable by you alone. The Google token refreshes itself on the server.

## Moving hosts later

Create the new server, run `server-setup.sh` on it, then from the Mac:
`rsync -az root@OLD:/opt/juno/data/ ./data/` (fresh copy of the database),
stop the old container, `scripts/deploy.sh root@NEW`. Ten minutes, no code changes.
