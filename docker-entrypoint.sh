#!/bin/sh
# Entrypoint: PUID/PGID dynamic user (linuxserver convention) for NAS deploys.
# - root + valid PUID  -> create user/group, chown /app/data if needed, drop privs
# - non-root or no PUID -> run uvicorn directly (local dev / `user:` directive)
set -e

PUID="${PUID:-}"
PGID="${PGID:-}"

if [ "$(id -u)" = "0" ] && [ -n "$PUID" ] && [ "$PUID" != "0" ]; then
  PGID="${PGID:-$PUID}"
  getent group "$PGID" >/dev/null || groupadd -g "$PGID" hac
  getent passwd "$PUID" >/dev/null || useradd -u "$PUID" -g "$PGID" -M -s /usr/sbin/nologin hac
  # chown only when owner differs (avoid full recursive chown on every start);
  # never touches read-only library mounts
  if [ -d /app/data ] && [ "$(stat -c %u /app/data)" != "$PUID" ]; then
    chown -R "$PUID:$PGID" /app/data
  fi
  exec gosu "$PUID:$PGID" uvicorn hac.main:app --host 0.0.0.0 --port 8000
fi

exec uvicorn hac.main:app --host 0.0.0.0 --port 8000
