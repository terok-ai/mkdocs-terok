# Versioned docs publishing

Every terok-`*` repo serves per-release documentation on GitHub Pages
with Material's version chooser: master merges refresh `/dev/`, and
each PyPI release adds a frozen `/<minor>/` snapshot. The machinery
lives in this package — the
[`publish-versioned-docs.yml`](https://github.com/terok-ai/mkdocs-terok/blob/master/.github/workflows/publish-versioned-docs.yml)
reusable workflow and the
[`mkdocs_terok.versions`][mkdocs_terok.versions] assembler it runs.

## The model: stateless assembly

There is no `gh-pages` branch and no stored site state. Each PyPI
release ships its built site as an immutable `docs-site.tar.gz` asset
on the GitHub release, and **every deploy reassembles the whole served
tree from scratch**: the newest final release of each served minor,
plus a fresh `/dev/` build, with `versions.json` (the chooser contract)
derived from the release list. A deploy is a pure function of the
release set and master — a botched one is fixed by re-running, and
retention is just a parameter: the newest `keep` minors are served
(default 6), older versions stay downloadable from their release
assets forever. Alphas never reach PyPI, so they mint no snapshot and
never appear in the chooser.

## Consumer wiring

A repo needs three pieces:

1. **docs.yml, build job** — build the site exactly as before and
   upload it as the `docs-site` artifact.
2. **docs.yml, publish job** — hand it to the reusable workflow:

    ```yaml
    publish:
      if: github.repository == 'terok-ai/<repo>' && (github.ref == 'refs/heads/master' || inputs.release)
      needs: build
      permissions:
        contents: write
        pages: write
        id-token: write
      uses: terok-ai/mkdocs-terok/.github/workflows/publish-versioned-docs.yml@vX.Y.Z
      with:
        release: ${{ inputs.release == true }}
    ```

    with a `workflow_call` trigger exposing the boolean `release`
    input. On a release call the same job first ships the snapshot
    asset, so its own plan already sees the new release.

3. **release.yml** — a `docs-version` job with `needs: pypi-publish`
   calling docs.yml with `release: true`. Only what users can
   `pip install` mints a docs version; gh-only releases publish
   nothing.

Repo settings: Pages source **GitHub Actions**, and the `github-pages`
environment must allow deployments from `v*` tags (release deploys run
on the tag ref).

In `properdocs.yml`, enable the chooser with
`extra.version.provider: mike` — that names the `versions.json`
contract Material reads, not the tool.

## One deployment per commit

GitHub Pages supports exactly one deployment per commit SHA: the API
rejects any other `pages_build_version`, and a second deployment of
the same SHA is silently ignored (or not — the behaviour is
unspecified). See
[actions/deploy-pages#383](https://github.com/actions/deploy-pages/issues/383).

The workflow therefore makes sure each SHA's one deployment is the
right one. A final `v*.*.*` tag on a pushed commit means a PyPI
release is in flight and its versioned publish owns that SHA, so the
branch-push deploy yields; alpha and untagged pushes deploy `/dev/` as
usual, which also covers gh-only releases. If a final tag ever lands
long after its merge (the release chain tags within seconds), the
snapshot simply appears with the next merge.
