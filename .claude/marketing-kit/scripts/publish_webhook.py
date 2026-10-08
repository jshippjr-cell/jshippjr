#!/usr/bin/env python3
import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def parse_args():
    parser = argparse.ArgumentParser(
        description="POST a JSON payload to a webhook URL, or preview it with --dry-run."
    )
    parser.add_argument("--url", help="Destination webhook URL. Falls back to MARKETING_WEBHOOK_URL.")
    parser.add_argument("--payload-file", help="Path to a JSON file. Reads stdin if omitted.")
    parser.add_argument("--header", action="append", default=[], metavar="NAME: VALUE",
                         help="Extra HTTP header. Repeatable.")
    parser.add_argument("--timeout", type=float, default=15, help="Request timeout in seconds (default: 15).")
    parser.add_argument("--dry-run", action="store_true", help="Print the request instead of sending it.")
    parser.add_argument("--confirmed", action="store_true",
                         help="Required to actually send. Only pass this after a human has seen the exact "
                              "payload and destination and explicitly said to proceed, in this conversation.")
    return parser.parse_args()


def load_payload(payload_file):
    try:
        if payload_file:
            with open(payload_file, "r", encoding="utf-8") as f:
                raw = f.read()
        else:
            raw = sys.stdin.read()
    except OSError as e:
        print(f"Could not read payload: {e}", file=sys.stderr)
        sys.exit(2)

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"Payload is not valid JSON: {e}", file=sys.stderr)
        sys.exit(2)


def parse_headers(header_args):
    headers = {"Content-Type": "application/json"}
    for entry in header_args:
        if ":" not in entry:
            print(f"Malformed --header (expected 'Name: Value'): {entry!r}", file=sys.stderr)
            sys.exit(2)
        name, value = entry.split(":", 1)
        headers[name.strip()] = value.strip()
    return headers


def main():
    args = parse_args()

    if not args.dry_run and not args.confirmed:
        print(
            "Refusing to send: pass --dry-run to preview the request, or --confirmed to "
            "actually send it. This script never sends without one of those being explicit.",
            file=sys.stderr,
        )
        sys.exit(2)

    url = args.url or os.environ.get("MARKETING_WEBHOOK_URL")
    if not url:
        print(
            "No webhook URL given. Pass --url or set the MARKETING_WEBHOOK_URL environment variable.",
            file=sys.stderr,
        )
        sys.exit(2)

    payload = load_payload(args.payload_file)
    headers = parse_headers(args.header)
    body = json.dumps(payload, indent=2).encode("utf-8")

    if args.dry_run:
        print("=== DRY RUN: no request sent ===")
        print("Method: POST")
        print(f"URL: {url}")
        print("Headers:")
        for name, value in headers.items():
            print(f"  {name}: {value}")
        print(f"Body (application/json, {len(body)} bytes):")
        print(body.decode("utf-8"))
        print("=== END DRY RUN ===")
        sys.exit(0)

    request = urllib.request.Request(url, data=body, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            status = response.getcode()
            reason = response.reason
            response_body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        try:
            error_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            error_body = ""
        print("Webhook returned non-2xx status", file=sys.stderr)
        print(f"Status: {e.code} {e.reason}", file=sys.stderr)
        print(f"Response: {error_body[:500] or '(empty body)'}", file=sys.stderr)
        sys.exit(4)
    except (urllib.error.URLError, OSError) as e:
        print(f"Failed to reach webhook URL: {e}", file=sys.stderr)
        sys.exit(3)

    print(f"Sent to {url}")
    print(f"Status: {status} {reason}")
    print(f"Response: {response_body[:500] or '(empty body)'}")
    sys.exit(0)


if __name__ == "__main__":
    main()
