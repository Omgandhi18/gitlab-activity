#!/usr/bin/env python3
"""
gitlab_graph_sync.py

Copies your gitlab.com contribution counts onto your GitHub contribution graph
by adding empty, dated commits to the repo this runs in. Nothing from GitLab is
copied: no code, repo names, titles or messages. Every commit is empty and its
message is just "GitLab activity".

Safe to re-run: for each day it only adds what is still missing.

Settings (environment variables):
  GIT_EMAIL      an email verified on your GitHub account            (required)
  GITLAB_TOKEN   personal access token with only the read_user scope.
                 With it: up to 3 years of history, works with a private
                 GitLab profile, and the token cannot read any code.
  GITLAB_USER    your gitlab.com username (required when there is no token).
                 Without a token the script reads your public calendar: the
                 last 12 months, and GitLab must have "Include private
                 contributions on my profile" turned on.
  GIT_NAME       author name for the commits   (default: your GitLab username)
  TIMEZONE       IANA zone used to group events into days in token mode,
                 e.g. Asia/Kolkata                             (default: UTC)
  SINCE          YYYY-MM-DD, ignore activity before this date
  MAX_PER_DAY    cap on commits per day, 0 = no cap               (default: 30)
  GITLAB_URL     (default: https://gitlab.com)
  DRY_RUN        set to 1 to print the plan without committing
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta, timezone

MARKER = "GitLab activity"
MARKER_PATTERN = "^GitLab activity$"
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
# Membership changes are not work, so they are not counted.
SKIP_ACTIONS = {"joined", "left", "expired"}


def plural(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def setting(name, default=None):
    value = os.environ.get(name, "").strip()
    return value or default


def http_get(url, token=None):
    headers = {"User-Agent": "gitlab-graph-sync", "Accept": "application/json"}
    if token:
        headers["PRIVATE-TOKEN"] = token
    request = urllib.request.Request(url, headers=headers)
    where = url.split("?")[0]
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
            headers = response.headers
    except urllib.error.HTTPError as error:
        hints = {
            401: "the token is wrong or has expired",
            403: "the token is missing the read_user scope, or access is blocked",
            404: "user not found, or the GitLab profile is private (use GITLAB_TOKEN)",
        }
        hint = hints.get(error.code)
        sys.exit(f"GitLab returned {error.code} for {where}" + (f": {hint}" if hint else ""))
    except urllib.error.URLError as error:
        sys.exit(f"Could not reach {where}: {error.reason}")
    try:
        return json.loads(body), headers
    except ValueError:
        sys.exit(
            f"{where} did not return JSON. If your GitLab profile is private, "
            "use GITLAB_TOKEN instead."
        )


def get_timezone(name):
    if name.upper() == "UTC":
        return timezone.utc
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:
        sys.exit(f"Unknown TIMEZONE: {name} (use a name like Asia/Kolkata)")


def parse_time(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def counts_from_api(base, token, tz, since):
    """Per-day counts of your own events, like GitLab's profile calendar."""
    me, _ = http_get(f"{base}/api/v4/user", token)
    username = me["username"]
    print(f"Reading events for GitLab user {username} with the token")
    counts = Counter()
    params = {"per_page": 100, "sort": "asc"}
    if since:
        # 'after' is exclusive and in UTC, so start early and filter by day below.
        params["after"] = (since - timedelta(days=2)).isoformat()
    page = "1"
    while page:
        params["page"] = page
        events, headers = http_get(
            f"{base}/api/v4/events?{urllib.parse.urlencode(params)}", token
        )
        if not events:
            break
        for event in events:
            if event.get("author_username") != username:
                continue
            action = (event.get("action_name") or "").split(" ")[0].lower()
            if action in SKIP_ACTIONS:
                continue
            day = parse_time(event["created_at"]).astimezone(tz).date()
            if since and day < since:
                continue
            counts[day] += 1
        page = (headers.get("X-Next-Page") or "").strip()
    return counts, username


def counts_from_calendar(base, user, since):
    """Per-day counts from the public profile calendar (last 12 months)."""
    data, _ = http_get(f"{base}/users/{urllib.parse.quote(user)}/calendar.json")
    counts = Counter()
    for day_text, count in data.items():
        day = date.fromisoformat(day_text)
        if since and day < since:
            continue
        if int(count) > 0:
            counts[day] = int(count)
    return counts


def git(*args, extra_env=None, check=True):
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(["git", *args], capture_output=True, text=True, env=env)
    if check and result.returncode != 0:
        sys.exit(f"git {args[0]} failed: {result.stderr.strip()}")
    return result


def existing_counts():
    """Commits this script already made, per day, and the current HEAD."""
    if git("rev-parse", "--verify", "-q", "HEAD", check=False).returncode != 0:
        return Counter(), None
    out = git("log", f"--grep={MARKER_PATTERN}", "--format=%ad", "--date=short").stdout
    head = git("rev-parse", "HEAD").stdout.strip()
    return Counter(date.fromisoformat(line) for line in out.split()), head


def add_commits(plan, name, email, head):
    """Write the empty commits on top of HEAD, keeping the repo's files as they are."""
    tree = git("rev-parse", "HEAD^{tree}").stdout.strip() if head else EMPTY_TREE
    parent = head
    for day, count in plan:
        # Noon UTC lands on the same calendar day in every timezone from UTC-11 to UTC+11.
        noon = datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc)
        for i in range(count):
            stamp = f"{int((noon + timedelta(seconds=i)).timestamp())} +0000"
            identity = {
                "GIT_AUTHOR_NAME": name,
                "GIT_AUTHOR_EMAIL": email,
                "GIT_AUTHOR_DATE": stamp,
                "GIT_COMMITTER_NAME": name,
                "GIT_COMMITTER_EMAIL": email,
                "GIT_COMMITTER_DATE": stamp,
            }
            args = ["commit-tree", tree, "-m", MARKER]
            if parent:
                args += ["-p", parent]
            parent = git(*args, extra_env=identity).stdout.strip()
    if parent and parent != head:
        git("update-ref", "HEAD", parent)


def main():
    base = setting("GITLAB_URL", "https://gitlab.com").rstrip("/")
    token = setting("GITLAB_TOKEN")
    user = setting("GITLAB_USER")
    email = setting("GIT_EMAIL")
    if not email or "@" not in email or email == "you@example.com":
        sys.exit("Set GIT_EMAIL to an email verified on your GitHub account")
    if user == "your-gitlab-username":
        user = None
    if not token and not user:
        sys.exit("Set GITLAB_TOKEN (recommended) or GITLAB_USER")
    tz = get_timezone(setting("TIMEZONE", "UTC"))
    since_text = setting("SINCE")
    since = date.fromisoformat(since_text) if since_text else None
    cap = int(setting("MAX_PER_DAY", "30"))
    dry_run = setting("DRY_RUN") == "1"

    if token:
        wanted, username = counts_from_api(base, token, tz, since)
    else:
        print(f"Reading the public contribution calendar of {user}")
        wanted, username = counts_from_calendar(base, user, since), user
    name = setting("GIT_NAME", username)

    if not wanted:
        print(
            "No GitLab activity found. Without a token, your GitLab profile must be "
            "public and 'Include private contributions on my profile' must be on."
        )
        return

    today = datetime.now(tz).date()
    wanted = Counter({day: n for day, n in wanted.items() if day <= today})
    if not wanted:
        print("No GitLab activity up to today")
        return
    have, head = existing_counts()
    plan = []
    for day in sorted(wanted):
        target = min(wanted[day], cap) if cap > 0 else wanted[day]
        missing = target - have.get(day, 0)
        if missing > 0:
            plan.append((day, missing))

    days = sorted(wanted)
    print(
        f"GitLab: {sum(wanted.values())} contributions on {plural(len(days), 'day')} "
        f"({days[0]} to {days[-1]})"
    )
    total = sum(count for _, count in plan)
    if not plan:
        print("Already up to date, nothing to add")
        return
    print(f"Adding {plural(total, 'commit')} across {plural(len(plan), 'day')}")
    if dry_run:
        for day, count in plan[:15]:
            print(f"  {day}: +{count}")
        if len(plan) > 15:
            print(f"  ... and {len(plan) - 15} more days")
        print("Dry run, nothing committed")
        return
    add_commits(plan, name, email, head)
    print("Done. Push the repo to GitHub to update your graph.")


if __name__ == "__main__":
    main()
