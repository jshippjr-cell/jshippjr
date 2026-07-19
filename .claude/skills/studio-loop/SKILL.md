---
name: studio-loop
description: The Scoring Stage build-verify loop — fresh demo server, door tokens, targeted tests, Playwright screenshots, review-panel prompts (Sonnet), and commit discipline. Use for every phase build, fix pass, and verification gate.
---

# Studio Loop — the repeatable build/verify cycle

Every phase of the Scoring Stage build repeats the same five steps. Use the
scripts in `scripts/` instead of retyping the commands; they encode the
environment quirks (container suspends, wedged pytest workers, chromium path,
commit-author hook) that previously burned time and tokens.

All paths below are relative to this skill directory
(`.claude/skills/studio-loop/`).

## 1. Demo server (fresh, seeded, doors printed)

```bash
bash scripts/demo.sh            # port 8093, fresh stage.db in $SCRATCH
bash scripts/demo.sh 8095       # alternate port (parallel instance)
```

Kills whatever holds the port (via `fuser`, never `pkill` with a
self-matching pattern), deletes the old DB, boots uvicorn with
`CHORDENTIAL_SEED_DEMO=1`, waits for `/healthz`, then prints **every door**:
composer rooms (`/creator/<token>`) and client portals
(`/project/<id>/delivery-portal?k=<token>`). Reviewer agents pollute the demo
DB — always re-run this before screenshots or a new review round.

Set `SCRATCH` to the session scratchpad dir first; defaults to
`/tmp/chordential-demo`.

## 2. Tests

```bash
bash scripts/test.sh                          # full suite, -n auto (~70s)
bash scripts/test.sh tests/test_creator_portal.py tests/test_delivery.py
```

Targeted runs are serial (`-n0`) — parallel workers wedge in `Thread.start()`
when the container suspends, so never leave a parallel run unattended. If a
run hangs >3 min, kill it and re-run the remaining files serially. The suite
must be green before any commit.

## 3. Screenshots

```bash
python scripts/shots.py out-prefix URL [URL...]          # 1440x900 desktop
python scripts/shots.py --mobile out-prefix URL [URL...] # 390x844
```

Uses the pre-installed chromium (`/opt/pw-browsers/...`) — never
`playwright install`. Full-page PNGs land at `<out-prefix>NN.png`.

## 4. Review panel — ALWAYS model "sonnet"

Cost rule (user directive): **every review agent runs on `model: "sonnet"`.**
The four standing reviewers and their re-verification rounds go through
`SendMessage` when the agent is alive, or a fresh `Agent` call with
`model: "sonnet"` when not. Prompt templates (verbatim charters for
Engineering, Design, Composer, Executive Producer) live in
`scripts/review-prompts.md`. Each reviewer must end with the verdict line
`VERDICT: production-ready — yes/no` plus a ranked findings list. The phase
gate is **all four yes**; otherwise consolidate findings into one ranked fix
pass, implement, and re-verify (re-seed the demo server first).

## 5. Commit + push

```bash
bash scripts/commit.sh "Message subject line"
bash scripts/commit.sh --push "Message subject line"
```

Commits with the required author (`Claude <noreply@anthropic.com>` — the
stop-hook rejects anything else) and appends the `Co-Authored-By:` /
`Claude-Session:` trailers used throughout history. `--push` pushes
`-u origin` to the current branch with 4x exponential-backoff retry. Never
include the model id in commit messages or repo artifacts.

## Standing environment facts

- Branch: `claude/admiring-mayer-u241h5` — commit directly, never switch.
- Test video for the stage must be **WebM/VP9** (this chromium has no H.264).
- `SETUPTOOLS_USE_DISTUTILS=stdlib` + `pip install --ignore-installed
  cryptography cffi` if `http-ece` ever needs rebuilding.
- Long unattended background runs die when the container suspends — keep
  turns short, verify in small steps.
