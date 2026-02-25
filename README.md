# GL Pipeline Monitor

Interactive TUI for monitoring GitLab MR pipelines. Built with Python + Textual.

## Prerequisites

- **Python 3.10+**
- **[uv](https://docs.astral.sh/uv/)** - python package manager that's 10-100x faster than pip. Preferred.
- **[pip](https://pypi.org/project/pip/)** - use pip if you don't want to use uv.
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

## Setup and Install

Clone this repository:
```bash
git clone https://github.com/erxand/gl-pipeline-monitor.git
cd gl-pipeline-monitor
```

The easiest way to sync the dependencies for this project is with `uv`:
```bash
# This command will create a .venv/ directory in the project with a per-project installation of python with the dependencies installed
uv sync
```

This will work too, but it clutters your global python install.
```bash
# This will install the dependencies globally, cluttering your python environments.
pip install -r requirements.txt
```

Symlink the program to to your `.local/bin/` so you can use it anywhere
```bash
mkdir -p ~/.local/bin
ln -s $(pwd)/main.py ~/.local/bin/glpipeline # Or name it whatever you'd like to call it on the command line
```

Ensure that `~/.local/bin/` is on your `$PATH`:
```bash
echo $PATH | grep ~/.local/bin
# If nothing appears, you need to add it to your path.
```
If it wasn't on your path, you need to edit your shell profile (usually `~/.zshrc` or `~/.bashrc`).
- add `export PATH="$HOME/.local/bin:$PATH"` somewhere in the file.
- Reload your terminal (quit it and start a new one, or `source` the file you just added the path to)

## Usage

Run from within a directory that is a GitLab repository (so `glab` can resolve the project):

```bash
glpipeline # Whatever you named the symlink from before
```

## Hotkeys

| Key       | Action                              |
|-----------|-------------------------------------|
| `a`       | Toggle between your MRs and all MRs |
| `d`       | Toggle showing draft MRs            |
| `r`       | Toggle auto-retry for selected MR   |
| `Enter`   | Expand/collapse job details         |
| `o`       | Open MR in browser                  |
| `f`       | Force refresh                       |
| `Esc`, `q`| Quit                                |

## Features

- Shows open MRs assigned to you with pipeline status
- Approval status column based on the MR's configured approval rules
- Expandable job detail view grouped by CI/CD stage
- Auto-retry failed jobs per MR (toggle with `r`)
- Auto-refreshes every 30 seconds, shows refresh indicator.
