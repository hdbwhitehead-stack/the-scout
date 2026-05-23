# Polymarket Scout

Scout finds high-probability prediction markets on Polymarket where the resolution payoff
is overwhelmingly priced one way, then ranks them by annualised return. It judges each
candidate with a small LLM agent (Claude Haiku) for resolution-risk, caches everything in
a local SQLite database, and renders a static HTML "docket" suitable for GitHub Pages.

The idea: edge cases where the market price implies near-certain resolution but the
absolute discount still compounds to a meaningful APR.

## Setup

```bash
uv sync
```

No API keys required for local use. The judge agent authenticates via your local
Claude Code session.

## Local usage

```bash
# Full pipeline: fetch → score → judge new candidates → render
uv run scout run

# Or step-by-step:
uv run scout fetch              # pull latest markets from Polymarket
uv run scout score              # report candidate count (no writes)
uv run scout judge              # judge unjudged candidates
uv run scout render             # write docs/index.html and docs/data.json
uv run scout list --top 20      # print the top 20 as a terminal table
```

After `scout run`, open `docs/index.html` in a browser.

## Configuration

Edit `config.toml`:

```toml
yield_threshold_apr = 0.05        # minimum annualised yield to qualify as a candidate
min_price = 0.90                  # minimum implied probability on the dominant side
max_days_to_resolution = 730      # maximum days until market resolves
model = "claude-haiku-4-5"        # judge model
```

## Architecture

- **Local pipeline** (`scout run`): fetches markets, scores them, judges new candidates
  through the Claude Code session, renders HTML/JSON.
- **CI refresh** (`.github/workflows/refresh.yml`): runs daily on a US-based GitHub
  Actions runner. Does `scout fetch` + `scout render` only — no judging in CI today (see
  caveat below). Commits refreshed `docs/` and `scout.db` back to `main`.

The SQLite database (`scout.db`) is committed to the repo so cached judgments survive
across runs and across machines. This file is intentionally **not** in `.gitignore`.

## Polymarket geo-block

Polymarket's Gamma API is ACMA-blocked in Australia (and a few other jurisdictions) at
the DNS level. If you're in a blocked region, run `scout fetch` / `scout run` through a
VPN. The GitHub Actions workflow runs from a US-based runner and is not affected.

## GitHub Pages setup

Enable Pages in repo settings:

1. Settings → Pages
2. Source: **Deploy from a branch**
3. Branch: `main`, folder: `/docs`

The docket will be served at `https://<user>.github.io/<repo>/`.

## Caveat: CI cannot judge new candidates yet

`scout judge` uses `claude-agent-sdk`, which authenticates via your local Claude Code
session, not via `ANTHROPIC_API_KEY`. CI therefore cannot run the judge step today.
Cached judgments in `scout.db` are still surfaced; new unjudged candidates appear in the
docket with empty risk fields.

To enable fully-autonomous CI judging, `src/scout/judge.py` needs a fallback path that
uses the `anthropic` SDK directly when `ANTHROPIC_API_KEY` is set. Once that's wired up,
add the key to GitHub Actions secrets and add a `scout judge` step to
`.github/workflows/refresh.yml`.
