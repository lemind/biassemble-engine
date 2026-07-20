#!/usr/bin/env bash
# Deploys the current working tree to the HF Space's git remote (`hf`) as a normal,
# non-destructive commit on top of whatever's already on hf/main — no --force, no
# history rewrite, origin and local branches untouched.
#
# WHY THIS EXISTS: vendor/wheels/llama_cpp_python-*.whl was committed as a raw
# (pre-LFS) blob in an old commit (6d4e508) that predates this repo's LFS tracking for
# *.whl and is now permanently part of published history (already on origin/GitHub).
# HF's git server hard-rejects any non-LFS object over 10MiB, so pushing that real
# history to a remote that's never seen it fails outright — and always will, since
# 6d4e508 never stops being an ancestor of the real branch. The one-time fix (already
# done 2026-07-19): seed hf/main with a single disconnected commit (0300cd1) containing
# just the current file tree, force-pushed once. From here on, hf/main has its own
# clean lineage with no oversized object in its ancestry — this script just appends a
# real child commit to that lineage every time, so every deploy after the first is an
# ordinary, non-forced, fast-forward push.
#
# HACK(hf-git-lfs-history): OBSERVED 2026-07-19 — vendor/wheels' pre-LFS blob blocks any
# push of *real* repo history to the hf remote; see above.
# REVISIT: if `git lfs migrate import --include="vendor/wheels/*.whl" --everything` is
# ever run to scrub the blob from history repo-wide (rewrites origin too — a deliberate,
# separate decision), delete this script and go back to `git push hf <branch>:main`.

set -euo pipefail
cd "$(dirname "$0")/.."

# Deploys HEAD's committed tree, not the working directory — an uncommitted edit here
# silently deploys stale content with no error (hit for real 2026-07-19: a Dockerfile
# fix was edited, deployed before being committed, and the push silently carried the
# old Dockerfile since `git rev-parse HEAD^{tree}` only sees commits). Refuse instead.
if [ -n "$(git status --porcelain)" ]; then
  echo "error: uncommitted changes present — commit first, or this deploy won't reflect what you just edited." >&2
  git status --short >&2
  exit 1
fi

git fetch hf main
parent=$(git rev-parse hf/main)
tree=$(git rev-parse HEAD^{tree})
msg="deploy: sync from $(git rev-parse --abbrev-ref HEAD) @ $(git rev-parse --short HEAD)"
new_commit=$(git commit-tree "$tree" -p "$parent" -m "$msg")

git push hf "${new_commit}:refs/heads/main"
echo "Deployed ${new_commit} to hf/main (plain fast-forward push, no --force, no rewrite)."
