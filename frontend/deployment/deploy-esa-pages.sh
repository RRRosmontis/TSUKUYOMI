#!/usr/bin/env bash
# Deploy the rrrosmontis.icu frontends to ESA Functions & Pages so the
# default-line traffic is served from ESA edge assets instead of fetching
# Cloudflare Pages on every request.
#
# Usage: ./scripts/deploy-esa-pages.sh [www|mail|sso|live|rosmanka|all]
# Requires ALIBABA_CLOUD_ACCESS_KEY_ID / ALIBABA_CLOUD_ACCESS_KEY_SECRET,
# or reads the migration credentials file.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ESA_CLI="${ESA_CLI:-/root/esa-cli/node_modules/.bin/esa}"
WORK="${ESA_WORK_DIR:-/tmp/esa-pages-build}"
CRED="${ESA_CRED_FILE:-/root/.config/akaros-cloud-migration/credentials.json}"

if [[ -z "${ALIBABA_CLOUD_ACCESS_KEY_ID:-}" && -f "$CRED" ]]; then
  eval "$(python3 - "$CRED" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
print("export ALIBABA_CLOUD_ACCESS_KEY_ID=%s" % json.dumps(d["esa_access_key_id"]))
print("export ALIBABA_CLOUD_ACCESS_KEY_SECRET=%s" % json.dumps(d["esa_access_key_secret"]))
PY
)"
fi

# key:source-dir:esa-project
TARGETS=(
  "www:www-rrrosmontis-icu-web:rrrosmontis-main"
  "mail:mail-rrrosmontis-icu-web:rrrosmontis-mail"
  "sso:sso-rrrosmontis-icu-web:rrrosmontis-sso"
  "live:live-rrrosmontis-icu-web:rrrosmontis-live"
  "rosmanka:rosmanka-rrrosmontis-icu-web:rrrosmontis-redirect"
)

deploy_one() {
  local name=$1 source=$2 project=$3
  local out="$WORK/$name"
  rm -rf "$out"; mkdir -p "$out/assets"
  rsync -a --exclude functions --exclude _redirects --exclude '*.bak*' "$ROOT/$source/" "$out/assets/"
  cp "$ROOT/esa-pages/$name/index.js" "$out/index.js"
  echo "==> $project: $(find "$out/assets" -type f | wc -l) files, $(du -sh "$out/assets" | cut -f1)"
  ( cd "$out" && "$ESA_CLI" deploy ./index.js -a ./assets -n "$project" -e production \
      -d "frontend assets on ESA edge" --no-minify --no-preview )
}

want="${1:-all}"
for t in "${TARGETS[@]}"; do
  IFS=: read -r name source project <<<"$t"
  [[ "$want" == "all" || "$want" == "$name" ]] || continue
  deploy_one "$name" "$source" "$project"
done
echo "done"
