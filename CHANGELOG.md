# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

A version's section here is what its GitHub release says. The release workflow
refuses a tag with no entry, so a release without notes is not a thing that can
happen.

## [Unreleased]

## [0.7.1] - 2026-09-12

### Added

- A GitHub release for every tag, created after the PyPI upload succeeds and
  carrying this file's section as its notes and the built sdist and wheel as
  its artifacts. Until now a tag published to PyPI and left nothing on GitHub,
  so somebody who arrived at the repository rather than at the package saw a
  project with no releases. The attached files are the ones the build produced
  and `publish` uploaded, not a rebuild that could differ from what is on PyPI.
- This changelog, with entries reconstructed for the versions that predate it.
- `scripts/changelog-section.sh`, which prints one version's section and fails
  if it has none. The release workflow uses it twice — to refuse a tag with no
  entry, and to render that entry as the release notes — so the check and the
  notes cannot disagree.
- `.github/dependabot.yml`, weekly for GitHub Actions and for the lockfile. The
  actions are pinned to commit SHAs, which is safe from a moved tag and blind
  to a patched vulnerability; something has to bring the new SHA to a pull
  request where a person can read it.

### Fixed

- The README and AGENTS.md said talanton was not on PyPI and had to be
  installed from git. It has been on PyPI since 0.6.0. Somebody following the
  setup instructions pinned a git ref instead of a version, which is the one
  thing those instructions exist to prevent.

### Note

- The engine is unchanged from 0.7.0 — nothing under `talanton/` moved. This
  version exists so that a tag produces the GitHub release that 0.6.0 and
  0.7.0, both published before the job existed, do not have.

## [0.7.0] - 2026-09-12

### Added

- `talanton publish <role>`, which renders an opening's board copy and its
  rubric into one file at an optional `[storage.openings]` location. Screening
  output landed in a shared location and the opening it was scored against did
  not, so reading an assessment meant opening the repository that holds the
  position file to see the bar. Write-only: nothing reads the published copy
  back, and the position file stays the source of truth.
- Automated PyPI publishing. Pushing a `v*` tag runs the same check gate main
  gets, builds, verifies the wheel installs and runs somewhere clean, and
  uploads via trusted publishing — no API token exists in the repository, in a
  GitHub secret, or on a laptop. The workflow refuses a tag whose version
  disagrees with `pyproject.toml`, because a version on PyPI can be yanked but
  never replaced.
- `LocationSpec.configured`, so an optional location that nobody wrote is
  distinguishable from one written out in full. Without it such a section
  cannot stay quiet in `check`, nor refuse to publish.

### Fixed

- **Inbound mail routes on `Delivered-To` alone.** `To`, `Cc` and
  `X-Original-To` are written by the sender and no longer sort anything, and
  only the first `Delivered-To` counts, so a forged header below it is ignored.
  A message with none is left unsorted with a warning saying why.
- **Screener prose is fenced before the root agent reads it.** Justifications,
  flags, probes and facts are applicant-derived text; they are now fenced in
  `list_candidates` and `get_candidate`, justifications are truncated on
  normalisation, and the root instruction says where that text came from.
- **A covering note is no longer filed as the CV.** An oversize attachment fell
  through to the body fallback; the message is now left unread and the log says
  why.
- **A hand-dropped document has a cost ceiling.** 20 MB on any document — the
  mail cap only ever guarded the mail path — at most 20 pages of a PDF, with a
  note when there were more, and docx/odt XML parsed with `defusedxml`, whose
  entity expansion is the reason.
- Names are folded before they are compared: NFKD, the ä/ö/ü/å/ø/æ spellings,
  and the spaces closed up, so Müller, Mueller, Muller and MarcoRossi each
  resolve to one person. `unknown` no longer counts as a recorded name, which
  had made the word unsayable in the digest.

### Changed

- `anthropic[vertex]` is an optional extra rather than a hard dependency. ADK
  imports it only for a `claude-*` model, and removing it outright would have
  broken the documented Anthropic-on-Vertex path.
- Dropped `company.locale`, `screening.reply_within_days` and
  `screening.default_role`: parsed, never read, and dead config misleads an
  operator into thinking it does something.
- The position is resolved once per tool call rather than three times per
  candidate.

## [0.6.0] - 2026-09-08

### Added

- First published version: the hiring pipeline end to end — draft a role,
  fetch what arrives, screen it against a rubric, and surface only the
  candidates worth a person's time. Google Drive and GCS for CV originals,
  IMAP for the apply mailbox, `dry_run` on by default everywhere, and
  candidate data gitignored by `talanton init` before the first CV arrives.

[Unreleased]: https://github.com/danielvogler/talanton/compare/v0.7.1...HEAD
[0.7.1]: https://github.com/danielvogler/talanton/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/danielvogler/talanton/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/danielvogler/talanton/releases/tag/v0.6.0
