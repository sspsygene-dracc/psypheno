# Tuesday session — Claude Code + git for dataset wranglers

> This document is the **agenda** for our Tuesday session **and** a **reference**
> you can re-read afterwards. It's written so Johannes (the facilitator) can
> use it as live demo notes — what to type, what to say, what to point at —
> and so you (the wrangler) can come back to it later, copy-paste the exact
> commands, and not have to remember every step from the meeting.
>
> Estimated time: **~90 minutes**.

---

## Goals

By the end of the session, you should be able to — *from your own laptop* —
do this end-to-end, without help:

1. Pick up a dataset ticket from
   [the GitHub issue tracker](https://github.com/sspsygene-dracc/psypheno/issues)
   and assign it to yourself.
2. Have Claude Code do most of the wrangling work for you (read the paper,
   draft `preprocess.py` and `config.yaml`, write `makeDoc.txt`).
3. Run a single-dataset local rebuild to test that your config actually
   loads.
4. Commit your work on a **branch named after the ticket**.
5. Rebase onto the latest `main`, fast-forward `main` to your branch, push.
6. Comment on the ticket with what landed, what was skipped, and why.

We will **not** cover this Tuesday (next time):

- Worktrees (running multiple Claude sessions side-by-side on different
  tickets).
- Deploying to dev / int / prod — we'll touch on it in an optional section
  at the end, but the deploy scripts stay in Johannes's hands for now.

---

## Why we're doing this (5 min)

> *Notes for Johannes — keep this brief, no slides.*

- **Today**, all of you edit the dev-server checkout directly, on `main`,
  on a single shared filesystem. That has worked, but it has two problems:
  1. We trip over each other — multiple people on the same `main` branch
     means one person's half-finished change blocks everyone else.
  2. You can't try a "what if I do it this way?" without breaking the
     live dev site for the rest of the team.
- **The fix is the standard pattern that software teams use:** each ticket
  gets its own *branch* on a *local* checkout. You experiment freely, you
  commit when it works, and only then does it land on `main` and reach
  the server.
- **Claude Code is a tool that fits this workflow well.** It can read the
  repo, talk to GitHub via `gh`, read paper PDFs (if you put them in
  `papers/`), and write `preprocess.py` + `config.yaml` for you. The big
  win is that 80% of dataset wrangling is mechanical — download the
  supplement, parse the spreadsheet, normalize gene names, write a YAML
  describing what's where — and Claude is good at exactly that. Your job
  shifts from *typing* to *judging*: did it interpret the columns right,
  did it pick the right species, did it sanity-check the row counts.

---

## 0. Facilitator pre-flight (Johannes only — not done in front of the room)

Before the meeting:

- [ ] Open this file in VSCode on the projector.
- [ ] In a browser tab, open
      https://github.com/sspsygene-dracc/psypheno/issues with filter
      `label:dataset is:open no:assignee`.
- [ ] **Pre-pick one or two safe demo tickets** — ideally a published paper
      (PMID, not bioRxiv) with an accessible supplementary table, single
      table, no exotic gene-symbol situations. Note the issue numbers.
- [ ] Have a terminal in `~/code/psypheno` ready, on `main`, clean
      `git status`.
- [ ] Have a Claude Code session ready to launch (don't pre-launch — show
      the launch live).
- [ ] Confirm everyone replied to the setup email; pair anyone who's
      stuck with someone who finished.

---

## 1. Verify everyone's setup (10 min)

Ask each person to run, in their own terminal:

```bash
git --version
gh --version
node --version
conda --version          # or python --version if they skipped miniconda
ls ~/code/psypheno
gh issue list --repo sspsygene-dracc/psypheno --limit 3
```

If any of these fails, **fix it now** — don't push through. The rest of
the session depends on these working.

Then have each person launch Claude (`claude` from inside `~/code/psypheno`)
and type:

```
/effort xhigh
```

This sets the thinking effort to maximum. Dataset wrangling involves reading
a paper, parsing a spreadsheet, and reasoning about our config schema all at
once — that's a workload where deeper reasoning visibly pays off, and we
want everyone on the same setting so the demo behaves consistently. The
setting persists in `~/.claude/settings.json`, so they only set it once.

(Verify by typing `/effort` with no argument; Claude should report `xhigh`.)
Then `/exit` to drop back to the shell.

---

## 2. Tour of the repo (5 min)

> *Live, in VSCode with `~/code/psypheno` open.*

Open `data/datasets/psychscreen/` and point at the three things wranglers
actually edit:

- `config.yaml` — what the website uses to build pages.
- `preprocess.py` — Python that turns raw downloads into a clean TSV.
- `makeDoc.txt` — a recipe for "how to download the raw data again", for
  anyone who comes back to this dataset in six months.

Then point at:

- `docs/adding-datasets.md` — the canonical wrangler guide. **The source
  of truth for the *what***. This tutorial is about the *how*: how you
  use Claude + git to get there faster.
- `docs/development.md` — local environment setup and deploy reference.

---

## 3. Set up your wrangler `CLAUDE.md` (10 min)

`CLAUDE.md` is a file at the repo root that Claude Code reads automatically
every time it runs in this directory. It's how we teach Claude the
conventions of this repo without having to repeat them in every prompt.

**`CLAUDE.md` is in `.gitignore`**, so your edits stay local — they don't
leak into commits or onto the public repo. Edit it freely. Add to it
whenever Claude does something you had to correct twice.

Below is a starter `CLAUDE.md` focused on **dataset wrangling**. Copy it
into a file at the repo root:

```bash
cd ~/code/psypheno
# open in your editor and paste the template below:
code CLAUDE.md
```

### Wrangler `CLAUDE.md` starter template

````markdown
# Project: SSPsyGene / Psypheno (wrangler view)

I add **datasets** to this project. I don't usually touch the web frontend
or the loader internals. When in doubt, prefer reading `docs/` over
guessing.

## Where things live

- Datasets: `data/datasets/<name>/` — each one has `config.yaml`,
  `preprocess.py`, `makeDoc.txt`, plus a `.gitignore` and the data files.
- Existing dataset examples to copy patterns from:
  - Simple human expression: `data/datasets/psychscreen/`
  - Mouse: `data/datasets/mouse-perturb-4tf/`
  - Zebrafish: `data/datasets/zebraAsd/`
  - Perturbation with two gene columns: `data/datasets/polygenic-risk-20/`
- Canonical guide: `docs/adding-datasets.md` — read it before suggesting
  config field values you're not sure about.

## How I work on a dataset ticket

- Tickets are on `sspsygene-dracc/psypheno`. Use `gh issue view NN
  --repo sspsygene-dracc/psypheno` to read one.
- I work on a **branch** named `dataset-NN-<short-name>`. Never directly
  on `main`.
- **First propose a plan** — don't write any files until I've reviewed
  the plan. Tell me: which paper, which supplementary table, what the
  columns are, what species, single-table or multi-table, perturbation
  or observational. Then wait for me to confirm before writing.
- Use `config_DRAFT.yaml` (not `config.yaml`) until I've reviewed and
  signed off. The loader's `rglob("config.yaml")` skips DRAFT files, so
  a draft can sit in the repo without breaking anyone's local rebuild.
  Promote to `config.yaml` only after sign-off.

## Hard rules I want enforced

- **Every column gets an informative `fieldLabel`.** "p-value" is useless;
  "Empirical p-value from 1000-permutation test (Smith et al. 2026,
  Methods §2.4)" is good. If you don't know what a column means, **ask
  me to download the paper PDF** to `papers/<author>_<year>.pdf` rather
  than guessing.
- **Gene-identifier resolution preference:** HGNC symbol > Ensembl (ENSG)
  > AC accession > everything else. If a column has both ENSG and a
  symbol, surface the symbol; preserve the original in `<col>_raw`.
- **Species:** human / mouse / zebrafish, set explicitly in
  `gene_mappings`. Mouse symbols starting lowercase need `to_upper:
  true`.
- **Perturbation datasets get two `gene_mappings`** — one
  `perturbed_or_target: perturbed`, one `perturbed_or_target: target`.
- **If anything is ambiguous, leave the file as `config_DRAFT.yaml`** and
  call out the open question at the top of the file. Loading datasets
  with unexplained data is worse than not loading them.

## Provenance

- Every dataset that downloads raw data needs a `makeDoc.txt` next to it
  with the actual `curl` / `wget` commands that fetched the inputs, plus
  a comment block noting source page and refresh cadence. Pattern from
  `data/datasets/sfari/makeDoc.txt`.
- The cleaned TSV gets a sidecar `<output>.preprocessing.yaml` written
  automatically by the `processing.preprocessing.Pipeline` — commit it.

## Fast iteration loop

To check my changes load without rebuilding the entire database:

```bash
cd ~/code/psypheno
SSPSYGENE_DATA_DIR=$(pwd)/data \
SSPSYGENE_CONFIG_JSON=processing/src/processing/config.json \
SSPSYGENE_DATA_DB=$(pwd)/data/db/sspsygene-claude.db \
sspsygene load-db --dataset NAME --no-index --skip-meta-analysis
```

`--no-index --skip-meta-analysis` skips the slow steps; useful for
"does my YAML even parse" checks. The full build (without those flags)
is needed before deploy.

## Things to NOT do without explicitly asking me

- Don't push to `origin` — I'll do that.
- Don't run `sspsygene deploy` — that's a server-touching action.
- Don't rebuild against the default `data/db/sspsygene.db` path — use
  the `sspsygene-claude.db` side path above so we don't fight whatever
  else is running.
- Don't close the GitHub issue when work lands. Dataset tickets stay
  open until the dataset is deployed and verified. I'll close it.

## Issue tracker workflow

- Assign yourself when you start: `gh issue edit NN
  --repo sspsygene-dracc/psypheno --add-assignee MY_GH_HANDLE`.
- Reference the ticket in commit messages: `Add Smith 2026 dataset
  (#142)`.
- After every dataset commit, comment on the ticket with: commit hash,
  dataset directory, source citation (DOI / PMID / supplementary table),
  row count, anything intentionally skipped and why, any "interpreted
  by analogy" decisions, and a "pending dev verify" note.
````

> *Live with the room: have everyone open a new file `CLAUDE.md` in the
> repo root, paste the template, replace `MY_GH_HANDLE` with their own
> handle, save. Confirm with `git status` that the file is **not** marked
> for commit (because it's gitignored).*

---

## 4. The dataset-ticket workflow, end-to-end (45 min)

This is the bulk of the session. We'll walk through it once together,
then each of you will try the same flow on a *different* ticket while
Johannes circulates.

### 4.1 Pick a ticket

In a browser, open
https://github.com/sspsygene-dracc/psypheno/issues?q=is%3Aopen+label%3Adataset+no%3Aassignee
and pick one. Note the issue number.

In your terminal, read it:

```bash
gh issue view 142 --repo sspsygene-dracc/psypheno
```

You should see the ticket title, body, and any comments printed in the
terminal.

### 4.2 Assign yourself

Convention: when you start a `dataset` ticket, assign it to your GitHub
handle so the team sees you've picked it up:

```bash
gh issue edit 142 --repo sspsygene-dracc/psypheno --add-assignee YOUR_GH_HANDLE
```

(Replace `YOUR_GH_HANDLE` with your actual GitHub username.)

### 4.3 Make a branch

Right now you're on `main`. **We never edit `main` directly.** Make a
branch named after the ticket:

```bash
# from inside ~/code/psypheno
git checkout main
git pull
git checkout -b dataset-142-smith-2026
```

What this does:

- `git checkout main` — switch to the `main` branch.
- `git pull` — fetch and merge the latest changes that others have
  pushed.
- `git checkout -b dataset-142-smith-2026` — create a new branch
  starting from the current commit, and switch to it. The name is
  free-form; the convention is `dataset-<issue#>-<short-name>`.

To see which branch you're on:

```bash
git branch --show-current
```

### 4.4 Hand the ticket to Claude

In the same terminal, from the repo root:

```bash
claude
```

A `>` prompt appears. The pattern Johannes uses (verbatim from real
sessions) is to paste the issue URL or number and ask for a plan
first:

> ```
> Let's work on this: https://github.com/sspsygene-dracc/psypheno/issues/142
>
> Please:
> 1. Read the ticket with gh.
> 2. Read docs/adding-datasets.md and pick one similar existing dataset
>    under data/datasets/ to use as a structural reference.
> 3. Propose a plan: which paper, which supplementary table, what the
>    columns mean, what species, what fieldLabels you'd use, whether
>    this is observational (target only) or perturbation (target +
>    perturbed). Don't write any files yet.
> ```

Why ask for a plan first? Because Claude's first read is sometimes
wrong, and **a wrong plan is much cheaper to correct than a wrong
implementation**. Common things to push back on at plan stage:

- "That's mouse, not human — the symbols you listed are mouse
  conventions."
- "Use the journal-published PMID, not the bioRxiv preprint."
- "The cell-type column is categorical, not numeric — we don't want
  to treat it as `scalar_columns`."
- "Skip Supplementary Table 4 — that's a WGCNA module list and we don't
  load module data."

When the plan is right, give Claude the green light:

> ```
> Plan looks good. Go ahead — create the files, write makeDoc.txt with
> the exact curl/wget commands you'd use, and write preprocess.py using
> the processing.preprocessing pipeline. Use config_DRAFT.yaml (not
> config.yaml) until I've reviewed.
> ```

> *Why `config_DRAFT.yaml`? The loader skips files named
> `config_DRAFT.yaml`. This means Claude can produce a draft without
> breaking anyone's local rebuild — including yours. We rename to
> `config.yaml` only once we're happy.*

### 4.5 Review what Claude produced

In VSCode you'll see new files under `data/datasets/<name>/`. Open each
one. Things to actively look for:

- **`config_DRAFT.yaml`:** does every column have a `fieldLabel`? Read
  each one and ask: would I, six months from now, know what this
  column means? If not, fix it (or ask Claude to). The bar is "an
  outsider could understand this without the paper open."
- **`preprocess.py`:** does the docstring describe the source? Are
  gene symbols normalized to the right species? Is `excel_demangle`
  on if the source is an Excel file (so `MARCH1` doesn't end up as
  `1-Mar`)?
- **`makeDoc.txt`:** would this script actually re-download the data
  on a fresh machine? Are there any hard-coded paths that would
  break?

If Claude got something wrong, tell it — natural language is fine:

> *"The `padj` column isn't FDR — the methods say it's the
> Bonferroni-corrected per-cell-type p-value. Update the fieldLabel
> and rename the column to `padj_bonferroni`."*

### 4.6 Run `preprocess.py` locally

```bash
conda activate sspsygene
cd data/datasets/<your-dataset>
python preprocess.py
head results.tsv
wc -l results.tsv
```

Sanity-check the output:

- Are gene symbols in the right column?
- Do the row counts match what the paper claims (within reason —
  filtering is normal)?
- Anything that looks like Excel date-mangling (`MARCH1` → `1-Mar`,
  `SEPT1` → `1-Sep`)?

### 4.7 Run a single-dataset load to test `config_DRAFT.yaml`

The loader **skips** `config_DRAFT.yaml`, so first promote it:

```bash
cd ~/code/psypheno
mv data/datasets/<your-dataset>/config_DRAFT.yaml \
   data/datasets/<your-dataset>/config.yaml
```

Then run the fast-iteration form:

```bash
SSPSYGENE_DATA_DIR=$(pwd)/data \
SSPSYGENE_CONFIG_JSON=processing/src/processing/config.json \
SSPSYGENE_DATA_DB=$(pwd)/data/db/sspsygene-claude.db \
sspsygene load-db --dataset <your-dataset> --no-index --skip-meta-analysis
```

> **Why the `sspsygene-claude.db` path?** If you wrote to the default
> `sspsygene.db`, you'd fight any other rebuild that's running on the
> same machine. The `sspsygene-claude.db` path is a safe scratch file.

> **Why `--no-index --skip-meta-analysis`?** They skip the two slowest
> stages (SQLite index creation and combined-p-value computation across
> datasets), so the test cycle is seconds rather than minutes. We're
> just checking *does my YAML parse and does the loader accept my
> data*, not building a production DB.

If it fails, read the error message; common ones:

- `FileNotFoundError` — `in_path` is wrong.
- `KeyError: '<column>'` — `column_name` in `gene_mappings` doesn't
  match an actual column header.
- `ValueError` about `shortLabel` — must be lowercase letters, digits,
  and underscores only.

If the loader passes, **sanity-check biology** before signing off. The
pattern Johannes uses is to ask Claude to confirm a known biological
result recapitulates — for an ASD postmortem-cortex dataset, for
instance, "PVALB should be down, GFAP up". For other datasets the
check is different. Whatever the dataset's headline result is, verify
your loaded data agrees with it before treating it as done.

If you can't resolve a column's meaning or units, **rename
`config.yaml` back to `config_DRAFT.yaml`** and call out the open
question at the top of the file. We don't ship datasets we don't
understand — better to leave the ticket open than to publish wrong
data.

### 4.8 Commit your work

```bash
git status                  # see what changed
git add data/datasets/<your-dataset>/config.yaml \
        data/datasets/<your-dataset>/preprocess.py \
        data/datasets/<your-dataset>/makeDoc.txt \
        data/datasets/<your-dataset>/.gitignore \
        data/datasets/<your-dataset>/results.tsv.preprocessing.yaml
git status                  # confirm — should NOT include the raw download or results.tsv itself
git commit
```

Your editor opens for the commit message. The convention (from real
recent commits) is:

```
Add <Author> <Year> <short description> dataset (#142)

PMID: 12345678 | <Journal> | DOI: 10.1038/...
Source: <Supplementary Table N>

Verified via single-dataset load-db; <one-line biology check that
recapitulates>.
```

The `(#142)` at the end of the **title line** is important — GitHub
uses it to link the commit to the ticket.

What we **don't** commit:

- Raw download files (Excel, large CSVs).
- The cleaned `results.tsv` itself (it's regenerable from
  `preprocess.py`).
- Anything else in your dataset's `.gitignore`.

If you accidentally added something you shouldn't have, unstage with
`git restore --staged path/to/file`.

#### Recommended alternative — let Claude commit for you

The Claude session you've been chatting with already knows what work it
just did, what files changed, and what convention `CLAUDE.md` says commit
messages should follow. So instead of typing the `git add` / `git commit`
dance by hand, you can just ask:

> ```
> Please commit the dataset work. Use our commit convention (PMID line,
> source citation line, one-line biology check). Stage only config.yaml,
> preprocess.py, makeDoc.txt, the .gitignore, and the
> *.preprocessing.yaml sidecar — do NOT stage the raw download or
> results.tsv. Show me the message before running `git commit`.
> ```

Claude will then run `git status` and `git diff --staged` itself, draft
a message, and (if you've granted it permission to run `git commit`) ask
before actually committing. This saves you typing and produces more
consistent messages — but **always read the proposed message and the
list of staged files before approving**. Claude is not infallible; it
sometimes wants to stage a file that should be gitignored, or omits the
PMID. The two-second sanity check is worth it.

If you'd rather Claude only does the staging and leaves the actual commit
to you, swap the last line for *"stage the files but don't commit; I'll
write the message myself"* — fine pattern too.

### 4.9 Rebase onto current `main`

While you were working, others may have pushed changes to `main`. You
need to replay your commits on top of theirs *before* you can merge:

```bash
git fetch origin main
git rebase origin/main
```

Two things can happen:

- **No conflicts:** rebase finishes silently. You're done.
- **Conflicts:** git stops and tells you which file. Open it in
  VSCode, find the `<<<<<<<` and `>>>>>>>` markers, pick the right
  resolution, save, then:

  ```bash
  git add path/to/file
  git rebase --continue
  ```

  If you get hopelessly stuck, `git rebase --abort` puts you back
  where you started — no harm done. Then ping in chat for help.

### 4.10 Merge to `main` with `--ff-only`

```bash
git checkout main
git merge --ff-only dataset-142-smith-2026
```

`--ff-only` means: "only let this merge happen if it's just a
fast-forward of `main` to my branch's tip." If git refuses with "Not
possible to fast-forward, aborting", it means you didn't rebase — go
back to step 4.9 and rebase.

> **Why the rebase + `--ff-only` discipline?** It keeps `main`'s
> history linear. Linear history makes `git log`, `git bisect`, and
> "who broke this last week?" much easier to reason about than a
> tangle of merge commits. The whole team relies on this — please
> follow it.

### 4.11 Push to GitHub

```bash
git push origin main
```

If GitHub rejects the push because someone else pushed in the meantime:

```bash
git pull --rebase
git push origin main
```

### 4.12 Comment on the ticket

After pushing, leave a comment with the commit hash and a structured
summary. **Don't close the ticket** — dataset tickets stay open until
the dataset is deployed to the dev server and you've verified it
there. Johannes will handle that and close.

```bash
gh issue comment 142 --repo sspsygene-dracc/psypheno --body "$(cat <<'EOF'
Landed in <commit-hash>.

- Dataset directory: `data/datasets/<your-dataset>/`
- Source: <full citation, DOI, PMID, supplementary table number>
- Files ingested: `<filename>` (N rows)
- Columns: <one-line summary of what the table contains>
- Skipped from this paper: <anything we deliberately didn't load — other
  supplementary tables, related cohorts, WGCNA modules — and *why*>
- Open questions / interpreted by analogy: <anything where I made a
  judgment call that should be revisited later, or "none">

Pending: deploy to dev + sign-off.
EOF
)"
```

(Replace `<commit-hash>` with the real hash — `git log -1 --format=%h`.)

### 4.13 Clean up your local branch (optional)

Once your changes are on `main`, the feature branch is dead weight:

```bash
git branch -d dataset-142-smith-2026
```

(`-d` will refuse if the branch isn't merged — that's a safety check.)

---

## 5. Rsync data files to the dev server (5 min)

Configs and `preprocess.py` reach the dev server through `git pull`. But
the **processed data files** (`results.tsv`, the raw downloads) are
gitignored, so they have to be copied separately or the dev `load-db`
will fail on a missing file.

After your commit lands on `main`:

```bash
rsync -av data/datasets/<your-dataset>/ \
    hgwdev:/hive/groups/SSPsyGene/sspsygene_website_dev/data/datasets/<your-dataset>/
```

(The trailing slashes matter — they sync directory *contents* into the
target rather than nesting one inside another.)

Then ping Johannes (or whoever's on dev) to actually rebuild the dev
database. For now, the rebuild stays in his hands.

---

## 6. Try it on a real ticket — group exercise (15 min)

Each of you picks a *different* open `dataset` ticket from the queue
and walks through 4.1–4.8 (pick → assign → branch → Claude → review →
preprocess → load-db test → commit). Pair up if you'd rather, or solo.
Johannes circulates and unblocks.

We'll do 4.9–4.13 (rebase, merge, push, comment) **once everyone is at
"I have a commit"** — rebasing and merging are easier as a group when
several branches need to land.

---

## 7. Optional: run the website locally (10 min if there's time)

Once your dataset has loaded into a local DB, you can also **see it on
the website** locally — gene pages, dataset table view, full-dataset
filtering — before anything ships to the dev server.

You'll need a recent local DB. If you don't have one, the easiest path
is to copy the dev DB from the server:

```bash
rsync -av hgwdev:/hive/groups/SSPsyGene/sspsygene_website_dev/data/db/sspsygene.db \
    ~/code/psypheno/data/db/sspsygene.db
```

Then start the web server (in a new terminal):

```bash
cd ~/code/psypheno/web
npm install                # one-time
SSPSYGENE_DATA_DB=$(cd .. && pwd)/data/db/sspsygene.db \
    npm run dev
```

Open http://localhost:3000 in your browser. As you rebuild the local DB
with `sspsygene load-db --dataset <your-dataset> ...`, the running web
server **auto-detects the new DB file** (inode/mtime check in
`web/lib/db.ts`) and re-opens its connection on the next request — no
restart needed.

This is the fastest way to actually *look at* your dataset on a gene
page before pushing.

---

## 8. Optional: testing locally (5 min)

The repo has a single test entry point:

```bash
cd ~/code/psypheno
scripts/test.sh             # fast suites — always safe to run
scripts/test.sh data-corr   # data-correspondence — needs a built DB
```

You don't need to run tests as part of every dataset commit — most of
the suite is about the loader and the website, not your dataset config.
But if you've changed `preprocess.py` for an existing dataset, or
modified anything under `processing/src/processing/preprocessing/`,
running `scripts/test.sh data-corr` is a good idea before you commit.

Full reference: `docs/development.md` → "Testing".

---

## 9. Optional: deploying a finished dataset to the server (10 min)

> *Tuesday-session note: we'll demo this only if there's time, and
> only Johannes runs it for now. The wranglers are reading this for
> reference, not to do it themselves yet.*

Once a dataset has landed on `main` *and* you've rsynced the data files
to the dev server (Section 5), the dev/int/prod databases need to be
rebuilt. This is what the `sspsygene deploy` CLI does — it takes care
of `git pull` on the server, optional preprocessing rerun, optional
`load-db`, optional service restart, all in one command, all rolled
through the right sequence (dev → int → prod).

The three forms you'll hear about:

```bash
# Deploy code + rebuild the DB on dev only (most common after a dataset
# commit; once verified, repeat with --instances int and then --instances prod):
sspsygene deploy --instances dev --load-db

# Re-run each dataset's preprocess.py on the server before load-db
# (use this when a preprocess.py change has landed and the cleaned
# data files on the server are now stale):
sspsygene deploy --instances dev --preprocess --load-db

# Code-only deploy with a service restart (for JS / web changes,
# not data changes):
sspsygene deploy --instances dev --restart
```

Useful flags:

- `--instances dev,int,prod` — comma-separated subset; order is
  ignored, deploy always rolls dev → int → prod.
- `--no-push` — skip the `git push` step (useful if you've already
  pushed manually).
- `--run-tests` — after each site's build, run `scripts/test.sh server`
  on psygene plus `scripts/test.sh e2e` against the deployed URL.
  Hard-aborts on first failure.

Full reference: `docs/development.md` → "CLI Reference".

For wranglers, the rule of thumb is: **always deploy to dev first, look
at the dev site, then promote to int, then prod.** Never deploy
straight to prod.

---

## 10. Sidebar: what the meta-analysis step is and why it matters (3 min)

You've seen the `--skip-meta-analysis` flag in the fast-iteration recipe.
Here's what it actually skips, so you know when to leave it on and when
to drop it.

The website's "most significant" page and the gene-search ranking are
powered by a **combined p-value** computed *across* datasets. For a
given gene, we take the per-dataset p-values from every table where the
gene shows up (with a sign — direction matters), and combine them using
**Cauchy combination** (perturbation side) and **Fisher's method**
(target side). The result is a single number that says "across all the
evidence in our database, how strong is the signal for this gene?". This
is what makes Psypheno more than just "a website with N tables on it" —
it's the cross-dataset synthesis.

Concretely, that means:

- **For dataset development** (testing your `config.yaml` parses, your
  preprocess output looks right, your single dataset loads): pass
  `--skip-meta-analysis`. The combined p-values for *other* datasets
  don't matter to you; you just want fast cycles.
- **For the build that ships** (the build that goes onto the dev / int /
  prod database): **do not skip**. The website needs the meta-analysis
  table for the "most significant" page and for ranking. A DB without
  meta-analysis will load and won't crash, but the gene pages and
  dataset breakdowns will be missing the cross-dataset numbers.

Same applies to `--no-index` — fine for local dev cycles, drop it for
the production build (the server queries are slow without indexes).

So the rhythm is: rebuild fast and dirty while you're iterating; rebuild
slow and clean when you're about to deploy.

---

## Cheat sheet (one-page reference)

| What | Command |
|------|---------|
| Read a ticket | `gh issue view NN --repo sspsygene-dracc/psypheno` |
| Assign yourself | `gh issue edit NN --repo sspsygene-dracc/psypheno --add-assignee YOUR_HANDLE` |
| Start a branch | `git checkout main && git pull && git checkout -b dataset-NN-<name>` |
| Launch Claude | `claude` |
| Stage files | `git add <file>` |
| Commit | `git commit` (then write a multi-line message) |
| Rebase onto `main` | `git fetch origin main && git rebase origin/main` |
| Merge to `main` | `git checkout main && git merge --ff-only <branch>` |
| Push | `git push origin main` |
| Comment on ticket | `gh issue comment NN --repo sspsygene-dracc/psypheno --body "..."` |
| Single-dataset rebuild | `sspsygene load-db --dataset NAME --no-index --skip-meta-analysis` |
| Full rebuild (pre-deploy) | `sspsygene load-db` |
| Rsync data to dev | `rsync -av data/datasets/NAME/ hgwdev:/hive/groups/SSPsyGene/sspsygene_website_dev/data/datasets/NAME/` |
| Deploy to dev | `sspsygene deploy --instances dev --load-db` *(Johannes runs)* |
| List branches | `git branch` |
| Delete merged branch | `git branch -d <branch>` |
| Promote DRAFT | `mv config_DRAFT.yaml config.yaml` |
| Demote to DRAFT | `mv config.yaml config_DRAFT.yaml` |

---

## After Tuesday

- Pick up your next ticket the same way. The first one or two will feel
  slow; by the third, this should be muscle memory.
- **Edit your `CLAUDE.md`** whenever Claude does something you had to
  correct twice. The whole point of `CLAUDE.md` is that you teach
  Claude your conventions *once*.
- If anything in this doc is wrong or missing, **say so** — we'll
  update it. This file is a living reference, not a one-shot.

— Johannes
