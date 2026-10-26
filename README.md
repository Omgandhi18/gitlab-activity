# GitLab activity

This repo mirrors my gitlab.com contribution calendar onto my GitHub contribution graph. It contains no code from GitLab: each commit is empty and dated to a day I was active there.

## Setup

1. Create a **private** GitHub repo (for example `gitlab-activity`) and add this README.
2. Add `gitlab_graph_sync.py` to the repo root and `sync.yml` at `.github/workflows/sync.yml`.
3. In `sync.yml`, set `GIT_EMAIL` to an email that is verified on your GitHub account (GitHub → Settings → Emails). Your `...@users.noreply.github.com` address works too.
4. Pick where the counts come from:
   - **Token (recommended):** in GitLab, go to your avatar → Edit profile → Access tokens, and create a token with only the `read_user` scope. That scope can't read code. In the GitHub repo, go to Settings → Secrets and variables → Actions and add it as a secret named `GITLAB_TOKEN`. This gives up to 3 years of history. GitLab tokens expire within a year, so replace the secret when that happens.
   - **No token:** set `GITLAB_USER` in `sync.yml`. In GitLab → Edit profile, turn on "Include private contributions on my profile" and keep the profile public. This only covers the last 12 months.
5. On the Actions tab, open "Sync GitLab activity" and click **Run workflow**. After that it runs every night.
6. On your GitHub profile, open **Contribution settings** above the graph and turn on **Private contributions**.

The graph can take up to 24 hours to update.

## Options

Add these under `env:` in `sync.yml`:

| Setting | What it does |
|---|---|
| `TIMEZONE` | Timezone used to group activity into days (default `UTC`; the workflow uses `Asia/Kolkata`) |
| `SINCE` | `YYYY-MM-DD`, ignore activity before this date |
| `MAX_PER_DAY` | Cap on commits per day (default `30`, GitLab's darkest shade); `0` = no cap |
| `DRY_RUN` | `1` prints what would be added without committing |

Running it again only adds what's missing, so it never double-counts a day.

To run it on your own computer instead: `GIT_EMAIL=... GITLAB_TOKEN=... python3 gitlab_graph_sync.py`, then `git push`.
