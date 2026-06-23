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
   in your **browser**, and assign it to yourself there.
2. Create the dataset directory and **download the paper + supplementary
   files into it first**, then have Claude Code do most of the wrangling
   work for you (read the paper, draft `preprocess.py` and `config.yaml`,
   write `makeDoc.txt`).
3. Let Claude run `preprocess.py`, fix the errors it hits, and sanity-check
   the output; then have Claude re-read its own draft against the paper as a
   verification pass.
4. Run a single-dataset local rebuild to test that your config actually
   loads.
5. Commit your work (Claude can draft the commit for you) on a **branch
   named after the ticket**, pushed to GitHub at creation time.
6. Rebase onto the latest `main`, fast-forward `main` to your branch, push.
7. Comment on the ticket (in the browser, or ask Claude) with what landed,
   what was skipped, and why.
8. Push the dataset out to the live servers: push the data files with
   `sspsygene push-data`, rebuild the dev DB with `sspsygene deploy`,
   **inspect it on the dev site**, then — for a **public** dataset — promote
   the verified dev build to prod with `sspsygene promote-dev-to-prod`
   (copies dev's DB straight over; don't rebuild on prod). For an
   **embargoed** dataset, deploy to int instead (int holds the things we
   can't or don't yet want to publish; prod is the public site). Close the
   ticket once it's live where it should be.

---

## 1. Verify everyone's setup (10 min)

Ask each person to run, in their own terminal:

```bash
git --version
gh --version
node --version
conda --version          # or python --version if they skipped miniconda
ls ~/code/psypheno
```

If any of these fails, **fix it now** — don't push through. The rest of
the session depends on these working.

Then have each person launch Claude within their repo (`cd ~/code/psypheno` and then type `claude`)
Once claude is running type:

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
  - Zebrafish: `data/datasets/zebra-autism/`
  - Perturbation with two gene columns: `data/datasets/polygenic-risk-20/`
- Canonical guide: `docs/adding-datasets.md` — read it before suggesting
  config field values you're not sure about.

## Python environment

- **All Python work runs in the `sspsygene` conda env.** Before running
  `sspsygene`, `python`, `pip`, `pytest`, or any `preprocess.py`, make sure
  the env is active: `conda activate sspsygene`. Don't run Python against
  the base interpreter or a system Python — the `sspsygene` CLI and its
  dependencies (pandas, R packages, etc.) only exist in that env.
- **If a Python package is missing, install it into the `sspsygene` env.**
  For common, well-known packages (e.g. `openpyxl`, `xlrd`, `requests`,
  `tqdm`) just install it — `conda install -y -c conda-forge <pkg>`, or
  `pip install <pkg>` if it's not on conda-forge — and keep going. For
  anything unusual, niche, or that pulls a large/compiled dependency
  tree, **ask me first** before installing.

## How I work on a dataset ticket

- Tickets are on `sspsygene-dracc/psypheno`. I read, assign, and comment
  on them in the **GitHub website**, not the terminal.
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

- **Every column gets an informative `fieldLabel`** — and these render as
  tooltips on the site, so keep them **uniform and concise**:
  - **One sentence, no more.** No multi-sentence paragraphs, no trailing
    notes or parentheticals stacked on. If it doesn't fit in one sentence,
    it's too long.
  - **Shape: what it measures + units/scale + source.** e.g. "Empirical
    p-value from a 1000-permutation test (Smith et al. 2026)" or
    "Log2 fold-change of expression vs. control (Smith et al. 2026)".
    "p-value" alone is useless; a three-line methods excerpt is too much.
  - Match the style of the labels already in the dataset so tooltips read
    consistently across columns.

  If you don't know what a column means, **ask me to download the paper
  PDF** to `papers/<author>_<year>.pdf` rather than guessing.
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
  automatically by the `processing.preprocessing.Pipeline` — it's gitignored,
  so don't commit it (the `generated:` timestamp churns every run; it's
  regenerated by `sspsygene preprocess` / deploy `--preprocess`).

## Fast iteration loop

To check my changes load without rebuilding the entire database:

```bash
cd ~/code/psypheno
conda activate sspsygene
SSPSYGENE_DATA_DIR=$(pwd)/data \
SSPSYGENE_CONFIG_JSON=processing/src/processing/config.json \
SSPSYGENE_DATA_DB=$(pwd)/data/db/sspsygene-claude.db \
sspsygene load-db --dataset NAME --no-index
```

`--no-index` skips the slow index-creation step; useful for "does my
YAML even parse" checks. The full build (without that flag) is needed
before deploy.

## Things to NOT do without explicitly asking me

- Don't push to `origin` — I'll do that.
- Don't run `sspsygene deploy` — that's a server-touching action.
- Don't rebuild against the default `data/db/sspsygene.db` path — use
  the `sspsygene-claude.db` side path above so we don't fight whatever
  else is running.
- Don't close the GitHub issue when work lands. Dataset tickets stay
  open until I've deployed; I'll close manually.

## Issue tracker workflow

- I assign tickets, read them, and comment on them in the **GitHub
  website**. You don't need to run `gh` for that — but you *may* draft a
  ticket comment for me to paste, or post one yourself if I ask.
- Reference the ticket in commit messages: `Add Smith 2026 dataset
  (#142)`. **The `(#NN)` in the commit title is required.**
- After every dataset commit, draft a ticket comment with: commit hash,
  dataset directory, source citation (DOI / PMID / supplementary table),
  row count, anything intentionally skipped and why, any "interpreted
  by analogy" decisions, and a "pending dev verify" note.
````

> *Live with the room: have everyone open a new file `CLAUDE.md` in the
> repo root, paste the template, save. Confirm with `git status` that the
> file is **not** marked for commit (because it's gitignored).*

---

## 4. The dataset-ticket workflow, end-to-end (45 min)

This is the bulk of the session. We'll walk through it once together,
then each of you will try the same flow on a *different* ticket while
Johannes circulates.

### 4.1 Pick a ticket

In a browser, open
https://github.com/sspsygene-dracc/psypheno/issues?q=is%3Aopen+label%3Adataset+no%3Aassignee
and pick one. Read its title, body, and any comments **right there in the
browser** — we do ticket reading, assigning, and commenting on the GitHub
website, not in the terminal. Note the issue number.

> **One-time: fetch the shared data files before your first `load-db`.**
> `sspsygene load-db` reads shared, non-dataset inputs — the gene-homology
> tables under `data/homology/` (HGNC, MGI, Alliance, …) — plus each dataset's
> raw/cleaned data files. Both are **gitignored**, so a fresh checkout doesn't
> have them and `load-db` would die with a `FileNotFoundError`. Pull them down
> from the dev server in one command (re-run any time something's missing — it
> only fetches what you don't already have):
>
> ```bash
> sspsygene pull-data            # shared homology inputs + every local dataset
> ```
>
> See [Fetching data files from the server](#fetching-data-files-from-the-server-pull-data)
> below for the full rundown (single-dataset pull, `--no-shared`, `--dry-run`).

### 4.2 Assign yourself

Convention: when you start a `dataset` ticket, assign it to yourself so
the team sees you've picked it up. On the ticket page, click **Assignees**
in the right-hand sidebar and select your GitHub handle.

(Doing this in the browser instead of the terminal keeps everything about
the ticket — reading, assigning, commenting, closing — in one place that
the whole team can see.)

### 4.3 Make a branch and push it

Right now you're on `main`. **We never edit `main` directly.** Make a
branch named after the ticket and push it to GitHub immediately:

```bash
# from inside ~/code/psypheno
git checkout main
git pull
git checkout -b dataset-142-smith-2026
git push -u origin dataset-142-smith-2026
```

What this does:

- `git checkout main` — switch to the `main` branch.
- `git pull` — fetch and merge the latest changes that others have
  pushed.
- `git checkout -b dataset-142-smith-2026` — create a new branch
  starting from the current commit, and switch to it. The name is
  free-form; the convention is `dataset-<issue#>-<short-name>`.
- `git push -u origin dataset-142-smith-2026` — publish the branch to
  GitHub right away and set it as the upstream (`-u`), so your work is
  backed up off your laptop from the start and later `git push` /
  `git pull` on this branch need no arguments.

To see which branch you're on:

```bash
git branch --show-current
```

### 4.4 Prepare the dataset directory and download the source files

**Do this before you bring Claude in.** Claude works far better when the
paper and the actual data files are already sitting on disk where it can
read them — rather than being told to go fetch them from a URL behind a
login wall or a Cloudflare check.

First, create the dataset directory. The naming convention:

- Lowercase letters, digits, and hyphens only — no spaces, no
  underscores, no capitals.
- Short and descriptive — usually an author/topic shorthand. Match the
  `<short-name>` you used in the branch where it makes sense.
- Examples already in the repo: `psychscreen`, `mouse-perturb-4tf`,
  `zebra-autism`, `polygenic-risk-20`, `sfari`.

```bash
cd ~/code/psypheno
mkdir -p data/datasets/smith-2026
```

Then download, **into that directory**, everything Claude will need to
understand the data:

- The **paper PDF**.
- The **supplementary methods** (often a separate PDF) — this is usually
  where the column definitions actually live.
- The **supplementary data files** themselves (the Excel / CSV / TSV
  tables the dataset is built from).

```bash
cd data/datasets/smith-2026
# e.g.
curl -L -o smith_2026.pdf            'https://…/article.pdf'
curl -L -o smith_2026_supp.pdf       'https://…/supplementary.pdf'
curl -L -o supp_table_s3.xlsx        'https://…/SuppTable3.xlsx'
```

If a source pushes back — login wall, Cloudflare, a single-page app with
no direct download link — **don't fight it**. Open the page in your
browser, download the file by hand, and drop it into the dataset
directory. You usually already have authenticated browser access, and the
manual hop is faster than scripting around the wall.

(The exact download commands are also what you'll record in `makeDoc.txt`
later — keep the URLs handy.)

### 4.5 Hand the ticket to Claude

In the same terminal, from the repo root:

```bash
claude
```

A `>` prompt appears. The pattern Johannes uses (verbatim from real
sessions) is to paste the issue URL, **point Claude at the files you just
downloaded**, and ask for a plan first:

> ```
> Let's work on this: https://github.com/sspsygene-dracc/psypheno/issues/142
>
> I've already created data/datasets/smith-2026/ and downloaded the paper,
> supplementary methods, and supplementary data into it. Use those files —
> don't try to re-download them.
>
> Please:
> 1. Read the ticket and the files in data/datasets/smith-2026/.
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

### 4.6 Review what Claude produced

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

### 4.7 Let Claude run `preprocess.py` and sanity-check the output

The recommended path is to **have Claude run `preprocess.py` itself**,
fix any errors it hits, and then look at the output to confirm it's
sensible. The Claude session already knows what the columns are supposed
to mean, so it's well placed to catch a preprocess that "ran fine" but
produced garbage. A prompt that works:

> ```
> Run preprocess.py for this dataset. If it errors, fix the script and
> re-run until it produces the cleaned TSV. Then show me: the column
> headers, a few example rows, and the row count — and tell me whether
> the gene symbols landed in the right column and whether the row count
> is in the ballpark the paper describes.
> ```

Then run an explicit **verification pass** — this is the cheap insurance
that catches the subtle mistakes:

> ```
> Now re-read the paper (and supplementary methods) against the
> config_DRAFT.yaml and the cleaned output you just produced. Check that
> each fieldLabel matches what the paper actually says the column is, that
> the species and gene-identifier handling are right, and that the
> dataset's headline biological result recapitulates in the output (for
> an ASD postmortem-cortex dataset, e.g., PVALB down, GFAP up). Report
> anything that doesn't line up — don't just tell me it looks good.
> ```

Asking Claude to *try to find problems* (rather than confirm it's fine)
is what makes this pass worth running.

**Manual fallback.** If you'd rather drive it yourself:

```bash
conda activate sspsygene
cd data/datasets/<your-dataset>
python preprocess.py
head results.tsv
wc -l results.tsv
```

Sanity-check the output by hand:

- Are gene symbols in the right column?
- Do the row counts match what the paper claims (within reason —
  filtering is normal)?
- Anything that looks like Excel date-mangling (`MARCH1` → `1-Mar`,
  `SEPT1` → `1-Sep`)?

### 4.8 Run a single-dataset load to test `config_DRAFT.yaml`

The loader **skips** `config_DRAFT.yaml`, so first promote it. Once
you're happy with the draft and Claude's verification pass came back
clean, rename it:

```bash
cd ~/code/psypheno
mv data/datasets/<your-dataset>/config_DRAFT.yaml \
   data/datasets/<your-dataset>/config.yaml
```

(This promotion is a real change to the repo and gets committed in the
next step — see §4.9. If you'd already committed the `config_DRAFT.yaml`
as a checkpoint, the rename is its own commit; don't leave both the DRAFT
and the live `config.yaml` floating in history.)

Then run the fast-iteration form:

```bash
SSPSYGENE_DATA_DIR=$(pwd)/data \
SSPSYGENE_CONFIG_JSON=processing/src/processing/config.json \
SSPSYGENE_DATA_DB=$(pwd)/data/db/sspsygene-claude.db \
sspsygene load-db --dataset <your-dataset> --no-index
```

> **Why the `sspsygene-claude.db` path?** If you wrote to the default
> `sspsygene.db`, you'd fight any other rebuild that's running on the
> same machine. The `sspsygene-claude.db` path is a safe scratch file.

> **Why `--no-index`?** It skips the slowest stage (SQLite index
> creation), so the test cycle is seconds rather than minutes. We're
> just checking *does my YAML parse and does the loader accept my
> data*, not building a production DB.

If it fails, read the error message; common ones:

- `FileNotFoundError` on `in_path` — either your `in_path` is wrong, or the
  dataset's gitignored data files just aren't on this machine yet. If the path
  looks right, the files probably live on the server — pull them with
  `sspsygene pull-data --dataset <your-dataset>`.
- `FileNotFoundError` on a `homology/...` path (HGNC / MGI / Alliance) — a
  shared input is missing. The error itself tells you to run `sspsygene
  pull-data`; do that once and re-run `load-db`.
- `KeyError: '<column>'` — `column_name` in `gene_mappings` doesn't
  match an actual column header.
- `ValueError` about `shortLabel` — must be lowercase letters, digits,
  and underscores only.

If you can't resolve a column's meaning or units, **rename
`config.yaml` back to `config_DRAFT.yaml`** and call out the open
question at the top of the file. We don't ship datasets we don't
understand — better to leave the ticket open than to publish wrong
data.

### Fetching data files from the server (`pull-data`)

`load-db` reads two kinds of files that **aren't in git**, so a fresh
checkout doesn't have them:

- **Shared/global gene-reference inputs** — the homology tables under
  `data/homology/` (HGNC, MGI, Alliance, …). These are the same for every
  dataset.
- **Per-dataset data** — each dataset's raw download(s) and the cleaned
  `<table>.tsv`/`.csv` outputs that `in_path` points at.

`sspsygene pull-data` rsyncs the missing ones **down** from the dev server
(`server → laptop`), without ever overwriting something you already have
locally. It's the **pull** half of the pair; [`push-data`](#5-get-your-dataset-onto-the-dev-server-5-min)
(Section 5) is the **push** half that sends *your* dataset's files back up.

```bash
sspsygene pull-data                       # shared inputs + every local dataset
sspsygene pull-data --dataset <name>      # one dataset (+ shared inputs)
sspsygene pull-data --no-shared           # dataset files only, skip homology
sspsygene pull-data --dry-run             # show what would transfer, write nothing
sspsygene pull-data --overwrite           # also refresh files you already have
```

By default it pulls from **dev** (effectively a superset of int and prod);
`--instance int|prod` picks another reference. You normally run plain
`sspsygene pull-data` once on a new machine, then again any time `load-db`
complains a file is missing.

### 4.9 Commit your work

The Claude session you've been chatting with already knows what work it
just did, what files changed, and what convention `CLAUDE.md` says commit
messages should follow. **The recommended path is to let Claude draft the
commit for you:**

> ```
> Please commit the dataset work. Use our commit convention (PMID line,
> source citation line, one-line biology check) and put the ticket number
> (#142) in the commit TITLE. Stage only config.yaml, preprocess.py,
> makeDoc.txt, and the .gitignore — do NOT stage the raw download,
> results.tsv, or the (gitignored) *.preprocessing.yaml sidecar. Show me
> the message and the staged file list before running `git commit`.
> ```

Claude will run `git status` and `git diff --staged` itself, draft a
message, and (if you've granted it permission to run `git commit`) ask
before actually committing. This saves typing and produces more
consistent messages — but **always read the proposed message and the
list of staged files before approving**. Claude is not infallible; it
sometimes wants to stage a file that should be gitignored, or omits the
PMID, or forgets the `(#NN)`. The two-second sanity check is worth it.

> **⚠️ The `(#NN)` ticket number MUST be in the commit *title*.** GitHub
> uses it to link the commit back to the ticket — e.g.
> `Add Smith 2026 ASD cortex dataset (#142)`. This is not optional. If
> Claude's drafted title is missing it, have it redo the message.

If you'd rather Claude only stages the files and leaves the actual commit
to you, swap the last line for *"stage the files but don't commit; I'll
write the message myself."*

**Manual fallback.** If you want to do it by hand:

```bash
git status                  # see what changed
git add data/datasets/<your-dataset>/config.yaml \
        data/datasets/<your-dataset>/preprocess.py \
        data/datasets/<your-dataset>/makeDoc.txt \
        data/datasets/<your-dataset>/.gitignore
git status                  # confirm — should NOT include the raw download, results.tsv, or the *.preprocessing.yaml sidecar (all gitignored)
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

What we **don't** commit:

- Raw download files (Excel, large CSVs).
- The cleaned `results.tsv` itself (it's regenerable from
  `preprocess.py`).
- Anything else in your dataset's `.gitignore`.

If you accidentally added something you shouldn't have, unstage with
`git restore --staged path/to/file`.

### 4.10 Rebase onto current `main`

While you were working, others may have landed changes on `main`. You
need to replay your commits on top of theirs *before* you can merge. The
simplest way to think about it: **refresh your local `main`, then rebase
your branch onto it.**

```bash
git checkout main
git pull                                  # update local main
git checkout dataset-142-smith-2026       # back to your branch
git rebase main                           # replay your commits on top of main
```

Two things can happen:

- **No conflicts:** rebase finishes silently. You're done.
- **Conflicts:** git stops and tells you which file. **Don't hand-resolve
  the `<<<<<<<` markers yourself** — let Claude analyze the conflict and
  propose a resolution:

  > ```
  > A git rebase stopped on a merge conflict in <file>. Please look at
  > both sides of the conflict and explain what each change is doing, then
  > propose how to resolve it. Don't run git add / git rebase --continue
  > until I've agreed.
  > ```

  If the conflict touches someone else's work and the right resolution
  isn't obvious, **coordinate with the other wrangler** (and Johannes)
  before continuing — better to ask than to silently clobber their edit.

  If you get hopelessly stuck, `git rebase --abort` puts you back where
  you started — no harm done. Then ping in chat for help.

### 4.11 Merge to `main` with `--ff-only`

```bash
git checkout main
git merge --ff-only dataset-142-smith-2026
```

`--ff-only` means: "only let this merge happen if it's just a
fast-forward of `main` to my branch's tip." If git refuses with "Not
possible to fast-forward, aborting", it means you didn't rebase — go
back to step 4.10 and rebase.

> **Why the rebase + `--ff-only` discipline?** It keeps `main`'s
> history linear. Linear history makes `git log`, `git bisect`, and
> "who broke this last week?" much easier to reason about than a
> tangle of merge commits. The whole team relies on this — please
> follow it.

### 4.12 Push to GitHub

```bash
git push origin main
```

If GitHub rejects the push because someone else pushed in the meantime:

```bash
git pull --rebase
git push origin main
```

(Your feature branch stays on GitHub too — we **keep branches around**,
we don't delete them after merging. If you want the remote branch to
reflect the rebased commits, `git push -f origin dataset-142-smith-2026`,
but that's optional.)

### 4.13 Comment on the ticket

After pushing, leave a comment with the commit hash and a structured
summary. **Don't close the ticket yet** — dataset tickets stay open
until you've pushed through to its live instance and verified the site.
You'll close it in Section 6.

Do this **in the browser** on the ticket page — or, easier, **ask Claude
to draft (or post) the comment**, since it already has all the details:

> ```
> Draft a ticket comment for #142 summarizing what we landed: the commit
> hash, the dataset directory, the source citation (DOI / PMID / supp
> table), the row count, anything we deliberately skipped and why, any
> "interpreted by analogy" calls, and a "pending dev verify" note. I'll
> paste it into the GitHub web UI.
> ```

A good comment looks like:

```
Landed in <commit-hash>.

- Dataset directory: `data/datasets/<your-dataset>/`
- Source: <full citation, DOI, PMID, supplementary table number>
- Files ingested: `<filename>` (N rows)
- Columns: <one-line summary of what the table contains>
- Skipped from this paper: <anything we deliberately didn't load — other
  supplementary tables, related cohorts, WGCNA modules — and *why*>
- Open questions / interpreted by analogy: <anything where I made a
  judgment call that should be revisited later, or "none">

Pending: deploy through dev/int/prod.
```

(Get the real short hash with `git log -1 --format=%h`.)

---

## 5. Get your dataset onto the dev server (5 min)

Your commit is on `main`, but the dev site
(https://psypheno-dev.gi.ucsc.edu) won't show the dataset until two
things happen: the gitignored data files reach the dev server, and the
dev SQLite DB gets rebuilt. Both are quick to do from your laptop.

> **Two habits to avoid in this section** — both are easy to fall into
> and both make life harder for the rest of the team:
>
> - **Don't SSH into psygene and edit files inside
>   `/hive/groups/SSPsyGene/sspsygene_website_*/`.** Those are shared
>   server checkouts that are supposed to track `main` exactly. If you
>   leave the tree in a "modified" state (or drop conflicting untracked
>   files in there), the next person's `sspsygene deploy` fails at
>   `git pull` until someone investigates and cleans it up. Every edit
>   you want to land — config tweak, typo fix, anything — should happen
>   in your **local clone**, get committed and pushed, and then reach
>   the server through the deploy below.
> - **Run `sspsygene deploy` from your laptop, not from psygene.** It's
>   designed to run against your local clone — it does the `git push`
>   from there and SSHes into psygene to do the rest. Running it on
>   psygene fails with confusing errors because the server checkout
>   isn't a branch you can push from.
>
> If you ever do need to touch a server checkout for an emergency, run
> `git status` before you leave and either commit + push from there or
> `git checkout -- <file>` to drop the change so the tree is clean.
>
> Also: one-time check that `ssh -J hgwdev psygene "umask"` prints
> `0002` and not `0022`. If it's `0022`, any file you create on psygene
> will be group-read-only and the next person's deploy will fail when it
> tries to update that file. Fix by adding `umask 0002` to your
> `~/.bashrc` on psygene. The pre-meeting setup doc walks through this.
>
> Also: your miniconda on psygene needs to live at one of the four
> paths `sspsygene deploy` searches (`$HOME/opt_rocky9/miniconda3/`,
> `$HOME/miniconda3/`, `$HOME/anaconda3/`, or `/opt/conda/`) — see the
> pre-meeting setup doc. If yours is elsewhere, a one-time `ln -s` into
> one of those paths is enough.

**Step 1 — push the gitignored data files with `sspsygene push-data`.**
Configs and `preprocess.py` reach the dev server through `git pull` in
the next step. But the processed data files (`results.tsv` and the raw
downloads) are gitignored, so they have to be copied separately or the
dev `load-db` fails on a missing file. From your laptop:

```bash
sspsygene push-data <your-dataset> --instance dev
```

This pushes **only** the gitignored data payloads — never `config.yaml`
or `preprocess.py`, which arrive via `git pull` — so the server's git
tree stays clean and the next person's `git pull` won't choke on a
locally-modified tracked file. It also creates the remote dataset
directory if it's missing and copies everything **group-writable**, so
the next wrangler can overwrite your files. (The old `rsync -av
data/datasets/<name>/ …` did none of this: it copied tracked files too,
dirtying the server tree, and left files mode-644 owned only by you.)
Name more than one dataset to push several at once; add `--dry-run` to
preview.

**Step 2 — deploy and rebuild the dev DB from your laptop.**

```bash
sspsygene deploy --instances dev --load-db
```

This pushes `main` to GitHub if you haven't already, `git pull`s on the
dev server, and rebuilds the dev SQLite DB; the running web process
auto-detects the new file. Takes a few minutes — the full rebuild runs
the indexing step that the fast-iteration recipe in Section 4.8
deliberately skipped.

> **One-time SSH setup:** the deploy's `git pull` runs *on* psygene and
> authenticates to GitHub from there, so psygene needs your GitHub key —
> either via agent forwarding (the deploy passes `ssh -A`) or a key you
> generate on psygene. Section 10c of the pre-meeting-setup doc walks
> through both, and it's the one-time fix for the old "git pull fails
> silently / asks for a password" problem. If `deploy` errors with
> `Permission denied (publickey)`, that's the section to read.

**Step 3 — inspect the dataset on the dev site.** This is a required
verification step, not a glance — broken data slips through here if you
skip it. Open https://psypheno-dev.gi.ucsc.edu and check:

- Your dataset shows up where it should — gene pages, the full-dataset
  table view, the dataset list.
- Column headers and tooltips read sensibly. Hover a header; the
  `fieldLabel` you wrote should appear, and it should read cleanly.
- A handful of representative genes (the paper's headline hits) carry
  the values you expect.
- The dataset's headline biology recapitulates on the live site (same
  check you ran locally in §4.7 — confirm it survived the full build).

If you want a second pair of eyes, you can ask Claude to hit the dev
API and cross-check counts/values against the paper for you — but you
should still look at the rendered pages yourself.

If something is off, fix it locally, commit, push, re-run `sspsygene
push-data <your-dataset> --instance dev`, and re-run `sspsygene
deploy --instances dev --load-db`. Iterate freely — dev exists to absorb
this kind of churn, and rebuilding it costs nothing but a few minutes of
wall time.

---

## 6. Publish to int and/or prod (5 min)

The dev site is your sandbox. Once a dataset looks right there, the
next step is to push it to one of the live instances:

- **int** — https://psypheno-int.gi.ucsc.edu. The internal instance.
  This is where datasets live that we **can't** or **don't yet want
  to** make public — embargoed data, things the consortium is still
  discussing, anything not yet cleared for the world. The site is
  access-controlled.
- **prod** — https://psypheno.gi.ucsc.edu. The public site.

A given dataset usually lands on **one of the two**, not both — int
if it can't be public yet, prod if it can. Some datasets sit on both
when that makes editorial sense. The "where does this go?" decision
is an editorial one, not a technical one; if you're not sure where a
particular dataset belongs, ask Max or Catharina.

**For int**, the flow is the same as the dev deploy — push the data files
from your laptop, then build on the server:

```bash
# Publish to int:
sspsygene push-data <your-dataset> --instance int    # push data files
sspsygene deploy --instances int --load-db               # deploy + rebuild
```

**For prod**, don't rebuild — **promote the verified dev build**. Since dev
is the staging instance for prod, `promote-dev-to-prod` copies dev's
already-built DB straight to prod, so prod serves byte-identical bytes (no
re-running `load-db`, no risk of drift, no data-file push needed — the built
DB already contains everything):

```bash
# Publish to prod (the standard path):
sspsygene promote-dev-to-prod                            # copy dev DB → prod
```

> If you run `sspsygene deploy --instances prod --load-db` instead, the deploy
> warns and asks for confirmation — rebuilding on prod is exactly what
> `promote-dev-to-prod` is meant to replace. Use the promote command.

Useful `sspsygene deploy` flags:

- `--instances dev,int,prod` — comma-separated subset; order is
  ignored. The three sites are independent deploys (not a chain) —
  they're iterated in dev → int → prod order purely for log
  readability.
- `--preprocess` — re-run each dataset's `preprocess.py` on the
  server before `load-db`. Use this when a `preprocess.py` change
  has landed and the server's cleaned data files are now stale.
- `--build` — `npm install` + `npm run build` on the server, then
  restart the Next.js web service. **You generally don't need this**
  — it's for JS / web code changes, and the restart step only works
  for the user who owns the systemd unit (currently Johannes). If a
  web rebuild needs deploying, ping Johannes.
- `--restart` / `--no-restart` — explicit override of the implicit
  restart. Data-only deploys don't need it (the web process
  auto-detects DB file swaps).
- `--run-tests` — after each site's build, run server tests on
  psygene plus `scripts/test.sh e2e` against the deployed URL from
  your laptop. Hard-aborts on first failure.

Full reference: [docs/development.md](../development.md) → "CLI Reference".

**A couple of things to keep in mind:**

- **Always inspect the dev site first.** dev is where you catch the
  loader misreading a column or a tooltip rendering wrong. Going
  straight to int or prod without that step is how broken data ends
  up on a live site.
- **Don't manually edit the DB on a server.** The DB on each
  instance is a cache of "what the loader does to the data files" —
  to fix something, fix the loader inputs locally, commit, and
  redeploy.

Once the dataset is live where it belongs, leave a final comment on the
GitHub issue (in the browser) and **close it there** — click **Close
issue** at the bottom of the ticket. A final comment like
`Live on int as of <commit-hash>.` (or "on prod" / "on int + prod")
before closing keeps the record clear.

If a dataset is later moved from int to prod (or vice versa), reopen
the ticket, redeploy, and close it again.

---

## 7. Try it on a real ticket — group exercise (20 min)

Each of you picks a *different* open `dataset` ticket from the queue
and walks through 4.1–4.9 (pick → assign → branch → download → Claude →
review → preprocess → load-db test → commit). Pair up if you'd rather,
or solo. Johannes circulates and unblocks.

We'll do 4.10–4.13 (rebase, merge, push, comment) **once everyone is at
"I have a commit"** — rebasing and merging are easier as a group when
several branches need to land.

Once everyone's pushed to `main`, we'll also walk through Section 5
together — rsync, dev deploy, inspect on the dev site. Section 6
(publish to int and/or prod) you can do at your desk afterward, or
now if we still have time and you're confident about where the
dataset belongs.

---

## 8. Optional: run the website locally (10 min if there's time)

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

## 9. Optional: testing locally (5 min)

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

## Cheat sheet (one-page reference)

| What | How |
|------|---------|
| Read a ticket | GitHub website → open the issue |
| Assign yourself | GitHub website → **Assignees** sidebar → your handle |
| Start a branch | `git checkout main && git pull && git checkout -b dataset-NN-<name> && git push -u origin dataset-NN-<name>` |
| Prep dataset dir | `mkdir -p data/datasets/<name>/`, download paper + supp + data into it |
| Launch Claude | `claude` |
| Run preprocess | ask Claude to run `preprocess.py`, fix errors, sanity-check output |
| Stage + commit | ask Claude to commit (read the message + staged files first); manual: `git add <file> && git commit` |
| Rebase onto `main` | `git checkout main && git pull && git checkout <branch> && git rebase main` |
| Merge to `main` | `git checkout main && git merge --ff-only <branch>` |
| Push | `git push origin main` |
| Comment on ticket | GitHub website (or ask Claude to draft/post) |
| Single-dataset rebuild | `sspsygene load-db --dataset NAME --no-index` |
| Full rebuild (pre-deploy) | `sspsygene load-db` |
| Pull data files (fresh machine) | `sspsygene pull-data` |
| Push data to dev | `sspsygene push-data NAME --instance dev` |
| Rebuild dev DB | `sspsygene deploy --instances dev --load-db` |
| Publish to int (internal / embargoed) | `sspsygene deploy --instances int --load-db` |
| Publish to prod (public, after dev verify) | `sspsygene promote-dev-to-prod` |
| Close ticket once live | GitHub website → **Close issue** |
| List branches | `git branch` |
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
</content>
</invoke>
