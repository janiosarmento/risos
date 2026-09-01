#!/usr/bin/env bash
#
# deploy.sh — sync this checkout to origin and restart the backend.
#
# Run it from anywhere; it cd's to its own directory first so git always
# operates on this repo:
#
#   ./deploy.sh
#   /var/www/rss.sarmento.org/deploy.sh
#   bash ~/some/path/deploy.sh
#
# Roughly equivalent to `git pull && sudo systemctl restart risos`, but it
# uses `fetch` + `reset --hard` so a dirty working tree on the server (stray
# deletions, tool cruft) can't block the deploy.
#
# Overridable via env:  RISOS_SERVICE (default: risos)
#                       RISOS_BRANCH  (default: main)

set -euo pipefail

SERVICE="${RISOS_SERVICE:-risos}"
BRANCH="${RISOS_BRANCH:-main}"

# --- move into the repo (this script's own directory), resolving symlinks ---
SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]:-$0}")"
REPO_DIR="$(dirname "$SCRIPT_PATH")"
cd "$REPO_DIR"

if ! git rev-parse --git-dir >/dev/null 2>&1; then
    echo "deploy: '$REPO_DIR' is not a git repository" >&2
    exit 1
fi

# --- run git as whoever owns the checkout (the repo is www-data's; running
#     git as root would create root-owned objects and wedge future pulls) ---
REPO_OWNER="$(stat -c '%U' "$REPO_DIR")"
if [ "$REPO_OWNER" = "$(id -un)" ]; then
    run_git() { git "$@"; }
else
    run_git() { sudo -u "$REPO_OWNER" -H git "$@"; }
fi

echo "deploy: repo=$REPO_DIR owner=$REPO_OWNER branch=$BRANCH service=$SERVICE"

echo "deploy: fetching origin..."
run_git fetch --prune origin

OLD_REV="$(run_git rev-parse --short HEAD)"
NEW_REV="$(run_git rev-parse --short "origin/$BRANCH")"

if [ "$OLD_REV" = "$NEW_REV" ]; then
    echo "deploy: already at $NEW_REV"
else
    echo "deploy: $OLD_REV -> $NEW_REV"
    run_git --no-pager log --oneline "HEAD..origin/$BRANCH" 2>/dev/null | sed 's/^/  /' || true
fi

echo "deploy: resetting working tree to origin/$BRANCH"
run_git reset --hard "origin/$BRANCH"

echo "deploy: restarting $SERVICE"
sudo systemctl restart "$SERVICE"

echo -n "deploy: waiting for $SERVICE to come up "
for _ in $(seq 1 30); do
    if systemctl is-active --quiet "$SERVICE"; then
        echo "— active"
        break
    fi
    echo -n "."
    sleep 1
done

if ! systemctl is-active --quiet "$SERVICE"; then
    echo
    echo "deploy: $SERVICE did not return to active — check the logs below" >&2
    sudo systemctl --no-pager --lines=25 status "$SERVICE" || true
    exit 1
fi

sudo systemctl --no-pager --lines=3 status "$SERVICE" | sed 's/^/  /'
echo "deploy: done — now at $NEW_REV"
