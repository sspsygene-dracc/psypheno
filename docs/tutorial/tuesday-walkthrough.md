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

TODO: git config --global user.name stuff etc

TODO: Claude modes --- shift tab --- auto mode

TODO: sspsygene conda env should install a bunch of useful python packages by default

TODO: tell Claude in CLAUDE.md that if it's missing python packages, it should
consider installing them and either just do it if they're common or ask the user
if it's OK to install them

TODO: create ticket of all the stuff that didn't work in the tutorial, collect
all the stuff I remember here, then send it to wranglers and tell them to add
more stuff that they remember was confusing or didn't work

TODO: decide on whether to work locally on remotely in a separate checkout

TODO: set appropriate environment variables in ~/.bashrc somewhere, we need
those before running. Just set them all, incl database file

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
7. Push the dataset out to the live servers: push the data files with
   `sspsygene rsync-dataset`, rebuild the dev DB on the server with
   `sspsygene wrangler-deploy`, eyeball it on the dev site, then
   deploy to int and/or prod depending on whether the dataset is publishable
   yet (int holds the things we can't or don't yet want to publish; prod is
   the public site). Close the ticket once it's live where it should be.

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

TODO: CLAUDE.md needs to be pointed to the conda environment

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
  automatically by the `processing.preprocessing.Pipeline` — it's gitignored,
  so don't commit it (the `generated:` timestamp churns every run; it's
  regenerated by `sspsygene preprocess` / deploy `--preprocess`).

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
  open until I've deployed; I'll close manually.

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

TODO: instead of reading/modifying tickets/commenting/assigning in your terminal, point users to the github.com website and make them do stuff there

TODO: need to set up environment variables

TODO: need to scp data/homology/other necessary files to localhost before
sspsygene load-db runs

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

TODO: before, create a data/datasets directory with naming convention 

TODO: before doing anything else, download the paper PDF, supplementary methods
PDF (if available) and all necessary supplementary data files to the newly
created dir. 

In the same terminal, from the repo root:

```bash
claude
```

TODO: edit the prompt to point Claude to the downloaded data

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

TODO: instead of running this manually, tell Claude to run it, fix any problems
that appear, and if it runs successfully, have a look at the output to see if
everything's working

```bash
conda activate sspsygene
cd data/datasets/<your-dataset>
python preprocess.py
head results.tsv
wc -l results.tsv
```

TODO: when creating your branch and comitting, push the branch with -u

TODO: just don't delete branches, let's keep them around

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

TODO: this needs a git commit again

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

TODO: if data files are missing, perhaps they exist on the server (e.g., the
homology file)

TODO: skip to the recommended alternative (letting claude commit for you) by
default

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
        data/datasets/<your-dataset>/.gitignore
git status                  # confirm — should NOT include the raw download, results.tsv, or the *.preprocessing.yaml sidecar (all gitignored)
git commit
```

TODO: note prominently that we want the ticket number in the commit message

Your editor opens for the commit message. The convention (from real
recent commits) is:

```
Add <Author> <Year> <short description> dataset (#142)

PMID: 12345678 | <Journal> | DOI: 10.1038/...
Source: <Supplementary Table N>

Verified via single-dataset load-db; <one-line biology check that
recapitulates>.
```

TODO claude verification pass after first pass

TODO inspect dataset on server

TODO tooltip length

TODO always run a recursive chmod o+w on the remote directories after doing
anything (deploy should do this automatically)

The `#142` at the end of the **title line** is important — GitHub
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
> preprocess.py, makeDoc.txt, and the .gitignore — do NOT stage the raw
> download, results.tsv, or the (gitignored) *.preprocessing.yaml sidecar.
> Show me the message before running `git commit`.
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

TODO: let's just switch to main, git pull, then switch to the branch again, and
rebase on the local main. This is less complicated mentally

```bash
git fetch origin main
git rebase origin/main
```

TODO: instead of the below, just write, instead of conflicts, let claude analyze
the situation and resolve with the other wranglers how to continue if necessary

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
summary. **Don't close the ticket yet** — dataset tickets stay open
until you've pushed through to prod and verified the live site. You'll
close it yourself in Section 6.

TODO: don't forget to comment in the browser, not on the command line. Or in
fact, better ask Claude to comment

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

Pending: deploy through dev/int/prod.
EOF
)"
```

(Replace `<commit-hash>` with the real hash — `git log -1 --format=%h`.)

### 4.13 Clean up your local branch (optional)

TODO: let's remove the cleaning up the branch stuff

Once your changes are on `main`, the feature branch is dead weight:

```bash
git branch -d dataset-142-smith-2026
```

(`-d` will refuse if the branch isn't merged — that's a safety check.)

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
> - **Don't run `sspsygene deploy` from psygene itself.** It's designed
>   to be run from your laptop, against your local clone — it does the
>   `git push` from there and SSHes into psygene to do the rest. Running
>   it on psygene fails with confusing errors because the server
>   checkout isn't a branch you can push from. The command meant to run
>   *on* psygene is `sspsygene wrangler-deploy` (no push, local build) —
>   that's what Step 2 below uses.
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

**Step 1 — push the gitignored data files with `sspsygene rsync-dataset`.**
Configs and `preprocess.py` reach the dev server through `git pull` in
the next step. But the processed data files (`results.tsv` and the raw
downloads) are gitignored, so they have to be copied separately or the
dev `load-db` fails on a missing file. From your laptop:

```bash
sspsygene rsync-dataset <your-dataset> --instance dev
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

**Step 2 — rebuild the dev DB from the server with `wrangler-deploy`.**
SSH into psygene and run the build there:

```bash
ssh -J hgwdev psygene
sspsygene wrangler-deploy --instances dev --load-db
```

Running the build *on* the server (rather than `sspsygene deploy`'s
SSH-from-your-laptop path) means `git pull` runs in your own
foreground shell with your own credentials — so if it ever needs a
password or asks a question, you see the prompt and can answer it. (The
laptop `sspsygene deploy` runs `git pull` non-interactively over SSH,
which swallows that prompt — it's why the pull failed silently for one
wrangler and hung asking for a password for another.) `wrangler-deploy`
then rebuilds the dev SQLite DB and the running web process auto-detects
the new file. Takes a few minutes — the full rebuild runs the indexing +
meta-analysis steps that the fast-iteration recipe in Section 4.7
deliberately skipped.

> **Maintainer shortcut:** Johannes can still run the whole thing from a
> laptop in one shot with `sspsygene deploy --instances dev --load-db`
> (push + SSH pull + load-db). Wranglers should prefer the
> rsync-dataset + wrangler-deploy split above — it's the flow that
> sidesteps the swallowed-credential-prompt problem.

**Step 3 — verify on the dev site.** Open
https://psypheno-dev.gi.ucsc.edu and check:

- Your dataset shows up where it should — gene pages, the full-dataset
  table view, the dataset list.
- Column headers and tooltips read sensibly. Hover a header; the
  `fieldLabel` you wrote should appear.
- A handful of representative genes (the paper's headline hits) carry
  the values you expect.
- The dataset's headline biology recapitulates on the live site.

If something is off, fix it locally, commit, push, re-run `sspsygene
rsync-dataset <your-dataset> --instance dev`, and re-run `sspsygene
wrangler-deploy --instances dev --load-db` on the server. Iterate freely
— dev exists to absorb this kind of churn, and rebuilding it costs
nothing but a few minutes of wall time.

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

The flow is the same as the dev deploy — push the data files from your
laptop, then build on the server — just with a different `--instance` /
`--instances` value:

```bash
# Publish to int:
sspsygene rsync-dataset <your-dataset> --instance int    # laptop
ssh -J hgwdev psygene
sspsygene wrangler-deploy --instances int --load-db       # server

# Publish to prod:
sspsygene rsync-dataset <your-dataset> --instance prod   # laptop
ssh -J hgwdev psygene
sspsygene wrangler-deploy --instances prod --load-db      # server
```

Useful `wrangler-deploy` flags:

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
  psygene. (The e2e suite is skipped there — no browsers on psygene;
  run it from your laptop with `sspsygene e2e-deployed <instance>`.)
  Hard-aborts on first failure.

Full reference: [docs/development.md](../development.md) → "CLI Reference".

**A couple of things to keep in mind:**

- **Always check the dev site first.** dev is where you catch the
  loader misreading a column or a tooltip rendering wrong. Going
  straight to int or prod without that step is how broken data ends
  up on a live site.
- **Don't manually edit the DB on a server.** The DB on each
  instance is a cache of "what the loader does to the data files" —
  to fix something, fix the loader inputs locally, commit, and
  redeploy.

Once the dataset is live where it belongs, leave a final comment on
the GitHub issue and close it:

```bash
gh issue comment 142 --repo sspsygene-dracc/psypheno \
    --body "Live on int as of <commit-hash>."   # or "on prod" / "on int + prod"
gh issue close 142 --repo sspsygene-dracc/psypheno
```

If a dataset is later moved from int to prod (or vice versa), reopen
the ticket, redeploy, and close it again.

---

## 7. Try it on a real ticket — group exercise (20 min)

Each of you picks a *different* open `dataset` ticket from the queue
and walks through 4.1–4.8 (pick → assign → branch → Claude → review →
preprocess → load-db test → commit). Pair up if you'd rather, or solo.
Johannes circulates and unblocks.

We'll do 4.9–4.13 (rebase, merge, push, comment) **once everyone is at
"I have a commit"** — rebasing and merging are easier as a group when
several branches need to land.

Once everyone's pushed to `main`, we'll also walk through Section 5
together — rsync, dev deploy, verify on the dev site. Section 6
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
| Rebuild dev DB | `sspsygene deploy --instances dev --load-db` |
| Publish to int (internal / embargoed) | `sspsygene deploy --instances int --load-db` |
| Publish to prod (public) | `sspsygene deploy --instances prod --load-db` |
| Close ticket once live | `gh issue close NN --repo sspsygene-dracc/psypheno` |
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
