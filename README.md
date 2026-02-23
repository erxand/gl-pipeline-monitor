# GL Pipeline Monitor

Interactive TUI for monitoring GitLab MR pipelines. Built with Python + Textual.

## Prerequisites

- **Python 3.10+**
- **[glab](https://gitlab.com/gitlab-org/cli)** - The GitLab CLI must be installed and authenticated.

### Installing glab

```bash
# macOS
brew install glab

# Linux (Homebrew)
brew install glab

# Or see https://gitlab.com/gitlab-org/cli#installation for other methods
```

### Authenticating glab

```bash
glab auth login
```

Follow the prompts to authenticate with your GitLab instance. The tool uses `glab` under the hood for all API access, so make sure `glab` is configured for the correct GitLab host and project.

You should be able to run `glab mr list` successfully in your target repo before using this tool.

## Setup

```bash
pip install -r requirements.txt
```

## Usage

Run from within a directory that is a GitLab repository (so `glab` can resolve the project):

```bash
python main.py
```

## Hotkeys

| Key     | Action                              |
|---------|-------------------------------------|
| `a`     | Toggle between your MRs and all MRs|
| `d`     | Toggle showing draft MRs            |
| `r`     | Toggle auto-retry for selected MR   |
| `Enter` | Expand/collapse job details         |
| `o`     | Open MR in browser                  |
| `f`     | Force refresh                       |
| `Esc`   | Quit                                |

## Features

- Shows open MRs assigned to you with pipeline status
- Approval status column based on the MR's configured approval rules
- Expandable job detail view grouped by CI/CD stage
- Auto-retry failed jobs per MR (toggle with `r`)
- Auto-refreshes every 30 seconds with countdown timer
