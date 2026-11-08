# Contributing

Thanks for helping with irrigation-ha. Bug reports, fixes and ideas are all welcome.

This integration opens and closes real water valves. A mistake can flood a garden or leave a zone running, so changes are reviewed carefully and the maintainer merges every pull request.

## Reporting a bug or asking for a feature

Open an [issue](https://github.com/jbuck2005/irrigation-ha/issues/new/choose) using one of the templates. For a bug, include your integration, Home Assistant and `irrigationd` versions, and the relevant lines from **Settings → System → Logs**.

Before posting logs or configuration, remove your token, host names and addresses. Security problems go through the [security policy](SECURITY.md) instead.

Problems with the daemon itself belong in [irrigationd](https://github.com/jbuck2005/irrigationd/issues).

## Making a change

1. Fork the repo and create a branch named `dev/<topic>`.
2. Keep each pull request to one change.
3. Run `python -m py_compile custom_components/irrigation/*.py` before committing.
   Run the test suite too with `pytest`; see [`tests/README.md`](tests/README.md) for setup.
4. Test with a running Home Assistant. A Docker install pointed at a simulated `irrigationd` is fine. Say in the pull request how you tested, and whether it ran on real valves.
5. Update the README if behaviour changes, and add a line to [`CHANGELOG.md`](CHANGELOG.md).
6. Open a pull request and fill in the template.

### Rules for every change

- An update must never clear a token that's already stored.
- Nothing home-specific goes in the repo: no addresses, host names, paths, names or real tokens. Use `your-long-random-token` in examples.
- Strip metadata from images before committing them.
- Stage files by name rather than with `git add -A`.

## Making a release

Only the maintainer makes releases. The version has to match in four places, or HACS can offer a version that doesn't install.

1. Set `version` in [`custom_components/irrigation/manifest.json`](custom_components/irrigation/manifest.json) to the new version, such as `1.2.2`.
2. In [`CHANGELOG.md`](CHANGELOG.md), rename **Unreleased** to `## 1.2.2 - YYYY-MM-DD` and start a new empty **Unreleased** section above it.
3. Merge both changes to `main` in one pull request.
4. Tag that commit on `main` with `v` and the version, such as `v1.2.2`, and push the tag.
5. Publish a GitHub release from the tag, with the changelog entry as its notes. HACS offers releases, not bare tags.
6. Update a test install through HACS, restart Home Assistant, and check the integration loads before telling anyone it's out.

Never delete or move a published tag, and never rewrite `main`'s history. Installs that point at an old tag stop working when it disappears.

## Code of conduct

Everyone taking part is expected to follow the [code of conduct](CODE_OF_CONDUCT.md).
