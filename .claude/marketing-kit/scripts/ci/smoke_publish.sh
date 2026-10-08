#!/usr/bin/env bash
# Smoke-tests both publish scripts with --dry-run and fake credentials: each
# must build its request and exit 0 without sending anything, and each must
# refuse to run with neither --dry-run nor --confirmed.
set -euo pipefail
cd "$(dirname "$0")/../.."

fake=fake-credential-0123456789abcdef
run() {
  local name=$1
  shift
  if ! out=$("$@" 2>&1); then
    echo "FAIL: $name"
    echo "$out"
    exit 1
  fi
  if ! grep -q "DRY RUN" <<<"$out"; then
    echo "FAIL: $name printed no dry-run preview"
    echo "$out"
    exit 1
  fi
  echo "ok: $name"
}

echo '{"hello": "world"}' >/tmp/smoke-payload.json
run webhook env MARKETING_WEBHOOK_URL=https://example.com/hook python3 scripts/publish_webhook.py --dry-run </tmp/smoke-payload.json

d=scripts/publish_direct.py
run linkedin env LINKEDIN_ACCESS_TOKEN=$fake LINKEDIN_AUTHOR_URN=urn:li:person:1 python3 $d --platform linkedin --text hi --dry-run
run x env X_ACCESS_TOKEN=$fake python3 $d --platform x --text hi --dry-run
run meta env META_PAGE_ACCESS_TOKEN=$fake META_PAGE_ID=1 python3 $d --platform meta --text hi --dry-run
run reddit env REDDIT_ACCESS_TOKEN=$fake REDDIT_USER_AGENT=smoke python3 $d --platform reddit --subreddit test --title hi --text hi --dry-run
run discord env DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/1/$fake python3 $d --platform discord --text hi --dry-run
run slack env SLACK_WEBHOOK_URL=https://hooks.slack.com/services/$fake python3 $d --platform slack --text hi --dry-run
run telegram env TELEGRAM_BOT_TOKEN=1:$fake python3 $d --platform telegram --chat-id 1 --text hi --dry-run
run devto env DEVTO_API_KEY=$fake python3 $d --platform devto --title hi --text hi --dry-run
printf 'fake' >/tmp/smoke-video.mp4
run youtube env YOUTUBE_ACCESS_TOKEN=$fake python3 $d --platform youtube --title hi --text hi --video-path /tmp/smoke-video.mp4 --made-for-kids false --dry-run
run instagram env META_PAGE_ACCESS_TOKEN=$fake IG_USER_ID=1 python3 $d --platform instagram --text hi --video-url https://example.com/v.mp4 --dry-run
run tiktok env TIKTOK_ACCESS_TOKEN=$fake python3 $d --platform tiktok --text hi --video-url https://example.com/v.mp4 --dry-run

# covers: TikTok takes a frame time, Instagram a frame time or an image URL
out=$(env TIKTOK_ACCESS_TOKEN=$fake python3 $d --platform tiktok --text hi --video-url https://example.com/v.mp4 --cover-ms 1500 --dry-run 2>&1)
grep -q '"video_cover_timestamp_ms": 1500' <<<"$out" || { echo "FAIL: tiktok --cover-ms"; echo "$out"; exit 1; }
echo "ok: tiktok cover"
out=$(env META_PAGE_ACCESS_TOKEN=$fake IG_USER_ID=1 python3 $d --platform instagram --text hi --video-url https://example.com/v.mp4 --cover-ms 1500 --dry-run 2>&1)
grep -q 'thumb_offset=1500' <<<"$out" || { echo "FAIL: instagram --cover-ms"; echo "$out"; exit 1; }
echo "ok: instagram cover"
if env YOUTUBE_ACCESS_TOKEN=$fake python3 $d --platform youtube --title hi --text hi --video-path /tmp/smoke-video.mp4 --made-for-kids false --cover-ms 0 --dry-run >/dev/null 2>&1; then
  echo "FAIL: youtube accepted --cover-ms"
  exit 1
fi
echo "ok: youtube refuses a cover"

# metrics: read-only, so it runs without --confirmed; checked here as a dry run
for platform in youtube instagram tiktok; do
  out=$(env YOUTUBE_ACCESS_TOKEN=$fake META_PAGE_ACCESS_TOKEN=$fake TIKTOK_ACCESS_TOKEN=$fake python3 $d --platform $platform --metrics --video-id 123 --dry-run 2>&1)
  grep -q "DRY RUN" <<<"$out" && ! grep -q "$fake" <<<"$out" || { echo "FAIL: $platform --metrics"; echo "$out"; exit 1; }
  echo "ok: $platform metrics"
done

if env DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/1/$fake python3 $d --platform discord --text hi >/dev/null 2>&1; then
  echo "FAIL: publish_direct.py ran with neither --dry-run nor --confirmed"
  exit 1
fi
echo "ok: refuses without --dry-run or --confirmed"
