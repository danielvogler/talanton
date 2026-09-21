# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

A version's section here is what its GitHub release says. The release workflow
refuses a tag with no entry, so a release without notes is not a thing that can
happen.

## [Unreleased]

### Changed

- The CV list in a shortlist mail is numbered, and carries its own count. A
  dozen candidate ids that differ only in their hex, each above a Drive URL
  that differs only in its file id, is a list nobody can keep their place in —
  the number is what makes "I stopped after 7" a place to come back to. The
  numbers are right-aligned so the column survives past nine.

- Each CV in a shortlist mail says when the application came in and by which
  route — `applied 2026-09-12, by email`, `arrived 2026-08-30, imported from
  jobs.ch`, or `arrival not recorded` for one dropped into the folder by hand.
  "The one from March, through the referral" is how an application is
  remembered; a candidate id is not.

  The route only, never the sender: a mailbox record's source is the address
  the application arrived from, and an address identifies as surely as a name
  does. The board or referrer behind an import identifies nobody and is shown.
  The records are read for the shortlisted candidates alone, so the mail costs
  one listing and one read per person written about rather than per CV on file.

## [0.10.0] - 2026-09-19

### Added

- A round-trip budget, asserted in the tests. A counting location records every
  `list` and `read`, and each operation is run against a small pool and one ten
  times the size with the counts required not to differ.

  These costs are invisible where they are written: `load_assessments()` reads
  like a dictionary lookup and is one request per assessment, and a local
  folder makes every one of them free — so the tests passed, a laptop was fast,
  and only an operator with a live Drive folder ever paid. A ceiling would have
  been raised by whoever tripped over it; an assertion that the cost must not
  scale can only be satisfied by fixing the cause.

### Changed

- Sending a digest no longer downloads every assessment in the opening three
  times over. Emailing about eighteen candidates from a pool of seventy-two
  took about five minutes before the mail went, because the CV links, the
  counts and the name check each answered their own question by reading the
  whole pool.

  The links now read only the candidates being written about, the footer is
  answered from listings alone, and the name check — which has to see every
  recorded name, since a name leaking for somebody who was not shortlisted is
  exactly as bad — reads the pool once rather than being one of three passes.
  On fifty candidates, a digest about three went from 150 reads to 53, or to 3
  where a deployment permits names and the guard does not run.

### Fixed

- An application nobody could read is now reported rather than silently
  absent. It is correctly left unassessed instead of scored zero, but
  `shortlist` ranks what is assessed — so an unreadable application was not
  ranked low, it was missing, and the digest read identically whether the
  shortlist was drawn from the whole pool or from most of it. The footer whose
  stated job is telling an empty pipeline from a broken one could not tell
  them apart.

  The digest now says how many could not be read and names their ids, which is
  what lets somebody go and ask those applicants for a file with a text layer.
  `status --full` says the same. The ids carry no identity, so this is
  unaffected by whether the deployment permits names.

  Worth stating why it is a fix rather than a note in the documentation: a
  scanned PDF is what you get from somebody who printed, signed and scanned
  their CV, which tracks career stage and country of origin far more than it
  tracks whether they can do the job. Dropping those applications without
  saying so is a selection effect, and a written rubric exists to rule those
  out.

  Recorded by the run that met them rather than recomputed for the digest:
  whether a document can be read is only knowable by reading it, and a footer
  is not the place to read every waiting application again.

- `shortlist` no longer follows a delivered shortlist with a report
  contradicting it. Both carried the same subject a minute apart, and an
  operator reading the later one as the truer one drops a candidate who
  cleared the bar.

  Delivery was read back from the runner's event stream, and `send_digest` is
  held by the correspondent — which `AgentTool` runs in a runner of its own,
  consuming those events and returning only text. No event the outer stream
  carried could ever say a digest went out, so the standing report fired on
  every successful run. It is now recorded where the delivery happens.

  A run that genuinely delivered nothing still reports, which is the point of
  the report: silence cannot distinguish an empty pool from a broken run.

## [0.9.0] - 2026-09-19

### Added

- Assessments record how they were produced: the model, the region it was
  served from, the talanton version, and the screening run they belong to. A
  score is one model's reading of one rubric, and "was the whole pool judged
  the same way?" was unanswerable from the files. A run driven by `next` and
  `record` records `by-hand` rather than a model id it did not use.

- `status --full` reports the pool above the roster: how candidates arrived and
  from where, how many of them were scored, and what judged them. It says so
  plainly when more than one model judged one pool.

### Fixed

- `assess` no longer reports success having done part of the work. A run that
  assessed ten of seventy-two ended with "I have reassessed all CVs", exit code
  zero. `StageFailedError` is documented as firing when a stage did not do its
  work, but what it checked was that the agent produced text — and an LLM
  always produces text, so it could never fire for the case it was named after.
  A plain run is now measured by the queue and a rescreen by whether every
  assessment carries that run's id. Candidates whose documents cannot be read
  are reported and exempted, since nothing is ever saved for them.

- The config is found at or above the working directory instead of only in it,
  so a deployment several levels down in a larger repository works without an
  environment variable in every shell. The walk stops at a repository
  boundary — a config above that belongs to another project. A command that
  needed a deployment and found none used to fall back to defaults silently,
  where an empty location is indistinguishable from a quiet week; it now says
  so.

### Changed

- Reading a whole pool's arrival records costs one listing rather than one per
  candidate. On Drive that was a round trip each, and the reconciliation the
  record exists for was the one call that did not finish.


## [0.8.1] - 2026-09-19

### Fixed

- `fetch` no longer merges different people into one candidate. 0.8.0 keyed an
  application on the sender's address, so every message from one address was
  one candidate — and an agency, a shared HR mailbox or a colleague forwarding
  on somebody's behalf sends for several people. Four applications arriving
  from one address became one candidate, and because each was written under the
  same id, the later ones overwrote the earlier ones. Three real applicants
  were destroyed, leaving nothing in the store or the output to notice.

  This was the reverse of the bug 0.8.0 set out to fix, and worse than it: a
  phantom candidate can be seen in a listing and discarded, a destroyed one
  cannot.

  An application is now keyed on the message — `Message-ID`, falling back to
  the mailbox's own id — which is the unit the multi-document grouping actually
  needs. One message with three attachments is still one candidate. The sender
  is recorded in the provenance record, where it belongs, rather than used as
  an identity.

  The cost, accepted deliberately: somebody who sends a second message with a
  document they forgot becomes a second candidate. That is a duplicate, which
  is visible and can be merged by a person who can see both. A merge is a
  decision taken on somebody's behalf without telling them.

- `write_documents` logs a warning when it writes over a candidate that already
  has documents. Legitimate on a re-read, never routine, and it is where a
  fault in whatever derives the id shows up first — silence there is what let
  the above destroy records rather than merely confuse them.


## [0.8.0] - 2026-09-19

### Added

- `talanton import <dir> --opening <n> --source <name>`, for applications that
  did not arrive at the apply mailbox — a batch downloaded from a job board,
  for instance. A loose file in the directory is one candidate; a subfolder is
  one candidate holding every document in it. Documents are renamed to the
  candidate id on the way in, as `fetch` does. `--dry-run` reports what would
  be imported and writes nothing.

  Off unless a deployment sets `[intake] import = true`. Whether to have a
  second intake path is a policy decision, and the command should not make it
  on anybody's behalf.

- A provenance record beside each candidate's documents, written by `import`
  and `fetch` alike: the date, the route, the board or sender, who ran it, and
  which documents it covers. `talanton show` prints it. Until now nothing
  persisted said when an application was received or by which route, so a CV
  forwarded into the apply mailbox was indistinguishable from one a candidate
  sent directly.

- `employers` on the assessment facts — the last few employers and titles, as
  the CV states them. A shortlist entry is easier to act on with them, and they
  name no one.

- `[shortlist] names`, off by default. The shortlist carries candidate ids and
  CV links and refuses a summary that names anybody, because email has no
  access control and a name in an inbox cannot be withdrawn. A deployment may
  decide otherwise; `check` then says so on every run.

### Fixed

- One application carrying several documents is now one candidate. `fetch`
  wrote one candidate per attachment, so an applicant who attached a CV, a
  covering letter and their certificates became three candidates — the covering
  letter scoring near zero and appearing in the shortlist as a weak applicant
  who does not exist, the certificates coming back `unreadable`.

  A message is now one application, and all of a candidate's documents are
  read and assessed together. One unreadable document among several no longer
  loses the others. (This shipped keyed on the sender, which was wrong; see
  0.8.1.)

- `assess` has no path to an outbox. It runs the `assessor` agent, which holds
  the same screener and rubric and no correspondent. With `dry_run = false`,
  `assess --rescreen` was observed mailing a shortlist to both operators
  without `shortlist` being run: every stage shared one toolset, so `dry_run`
  was the only thing in the way. `shortlist` is unchanged and still sends.

### Changed

- `talanton status` counts candidates rather than files.

- Stored CVs are unchanged. A candidate's first document keeps the name it
  always had and only later documents carry a suffix, so no migration is
  needed and existing assessments stay attached.

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
