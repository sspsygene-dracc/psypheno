# Pre-meeting setup for Tuesday's Claude + Git session

> **Suggested email subject:** "Setup for Tuesday's Claude/Git session — please run before the meeting"

Hi all,

On Tuesday we're going to spend the meeting working through how to use **Claude
Code** as a "dataset-wrangler assistant" on your laptop, and how to use **git
branches** so we can stop stepping on each other while we add datasets. The
goal: by the end of the session, each of you should be able to pick up a
ticket, do the work locally with Claude's help, and merge it cleanly onto
`main` without breaking anyone else's work.

To make the meeting useful (rather than spending all of it on installs), please
run through the checklist below **before Tuesday**. Most of it is one-liners.
**If anything fails, just reply to this email** with the exact error message
and which step failed — I'd much rather fix it on Monday afternoon than spend
Tuesday's time on it.

Estimated time: **30–45 minutes** if everything goes smoothly.

The agenda for Tuesday is in `docs/tutorial/tuesday-walkthrough.md` once you've
cloned the repo. I'll also send it in a follow-up email right now. You don't
need to read it beforehand, but you're welcome to.

---

## Prerequisites you probably already have

- A Mac running macOS.
- A GitHub account, with read access to
  https://github.com/sspsygene-dracc/psypheno. If you can open that link and
  see the issues tab, you're set.
- An Anthropic / Claude account. If you don't have one yet, reply to this
  email and Max will get you sorted.

---

## 1. Install the macOS command-line tools

Open **Terminal.app** (`Cmd+Space`, type "terminal", Enter) and run:

```bash
xcode-select --install
```

If a popup appears, click "Install" and accept the license. If it says
"command line tools are already installed", you're already good.

---

## 2. Install Homebrew

[Homebrew](https://brew.sh/) is the standard package manager on macOS. Most of
the rest of this list is one `brew install` away once it's set up. To install:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

When it finishes, follow the on-screen instructions at the very end of the
install output. There will be **two `eval` lines** — copy and paste both into
your terminal to add `brew` to your `PATH`. (They look like
`eval "$(/opt/homebrew/bin/brew shellenv)"`.)

Test:

```bash
brew --version
```

---

## 3. Install git, gh, Node.js, and VSCode

```bash
brew install git gh node
brew install --cask visual-studio-code
```

Test that each one works:

```bash
git --version
gh --version
node --version
code --version
```

---

## 4. Authenticate `gh` with GitHub

`gh` is GitHub's command-line tool. We use it to read tickets, leave comments,
and assign issues without ever leaving the terminal. Authenticate it once:

```bash
gh auth login
```

When prompted, pick:

- **GitHub.com** (not GitHub Enterprise)
- **HTTPS**
- **Yes** when it asks about authenticating Git as well
- **Login with a web browser**

A one-time code will appear in your terminal — `gh` will paste it into the
browser for you. Click through, approve, done.

Test (this should print a few open issues):

```bash
gh issue list --repo sspsygene-dracc/psypheno --limit 5
```

If you get a permissions error, ping me and I'll add you to the repo.

---

## 5. Install Python via miniconda

The processing pipeline needs Python 3.11+. The cleanest way to get it is
miniconda:

```bash
brew install --cask miniconda
conda init "$(basename "$SHELL")"
```

(That `conda init` line auto-detects whichever shell you use — bash, zsh, fish,
whatever. No need to know what your default shell is.)

After `conda init`, **close your terminal and open a new one** so the changes
take effect. Then:

```bash
conda --version
```

> Already have a Python setup you're happy with (pyenv, system Python, etc.)?
> Skip miniconda — anything that gives you Python 3.11+ is fine.

---

## 6. Clone the repo

Pick a directory you don't mind cluttering. The convention is `~/code/`:

```bash
mkdir -p ~/code && cd ~/code
git clone https://github.com/sspsygene-dracc/psypheno.git
cd psypheno
```

Test (you should see the project's top-level layout):

```bash
ls
# should show: data  docs  processing  web  scripts  README.md  ...
```

---

## 7. Install Claude Code

Install the CLI globally:

```bash
npm install -g @anthropic-ai/claude-code
```

Then start it once from inside the repo and log in:

```bash
cd ~/code/psypheno
claude
```

It'll prompt you to log in via the browser the first time. After login, **set
the thinking level to maximum** by typing this command at the `>` prompt:

```
/effort xhigh
```

This makes Claude think harder before acting — the difference is noticeable on
dataset wrangling, where Claude has to reason over a paper PDF, a spreadsheet,
and our config schema all at once. The setting persists across sessions
(saved to `~/.claude/settings.json`), so you only need to do it once.

Then type `/exit` to close. We'll come back to this together on Tuesday.

---

## 8. Install the Claude Code VSCode extension

From the repo directory, open VSCode:

```bash
code .
```

Then in VSCode:

1. Open the Extensions panel (`Cmd+Shift+X`).
2. Search for "Claude Code".
3. Install the official extension from Anthropic.

You'll see a Claude icon appear in the left sidebar.

---

## 9. (Optional but very nice) Set up the Python venv for the processing pipeline

This isn't strictly required for Tuesday, but doing it now will save us 10
minutes during the session:

```bash
cd ~/code/psypheno
conda create -y -n sspsygene python=3.13
conda activate sspsygene
cd processing
pip install -e .
```

Test:

```bash
sspsygene --help
```

---

## What to do if something fails

**Reply to this email** with:

1. Which step number failed.
2. The exact error message — please copy-paste from your terminal rather than
   paraphrasing or screenshotting.
3. The output of `uname -m` (tells me Apple Silicon vs. Intel) and
   `sw_vers` (your macOS version).

I'd much rather fix it Monday afternoon than spend Tuesday morning on it.

---

## What we'll do on Tuesday (preview)

- A short tour of the repo, focused on the dataset-wrangling parts.
- Set up a starter `CLAUDE.md` so Claude understands our conventions.
- Pick a real ticket from the issue tracker, assign it to ourselves, and walk
  it through end-to-end: branch → Claude does the wrangling → review → test
  locally → commit → rebase → merge → comment on the ticket → rsync data to
  the dev server → rebuild the dev DB → verify on the dev site → deploy to
  int and/or prod (int holds embargoed/internal-only data, prod is the public
  site) → close the ticket.
- Optional add-ons (covered if there's time): how to start the web server
  locally to look at your dataset before pushing, and how the meta-analysis
  step fits in.

See you Tuesday — and please ping me if anything in the setup is unclear or
breaks.

— Johannes
