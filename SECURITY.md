# Security

## Reporting

Report a vulnerability privately through
[GitHub security advisories](https://github.com/danielvogler/talanton/security/advisories/new).
Please do not open a public issue for anything exploitable.

## What this repository is careful about

talanton reads other people's job applications. The people whose data it
handles never chose this tool, cannot see what it does, and are not the ones
running it — so the guards are the product rather than a nicety, and every one
of them is a test rather than a promise.

### Candidate data never lands in git

- **The locations are gitignored before the first CV arrives.** `talanton init`
  writes `cvs/` and `assessments/` into `.gitignore` at setup, not afterwards.
- **A pre-commit hook refuses candidate data outright.** `.gitignore` is walked
  straight past by `git add -f`, and it cannot help with a CV saved somewhere
  new or a real address pasted into a test. `scripts/refuse_candidate_data.py`
  refuses any document outside the invented example set, and any email address
  that is not a reserved placeholder.
- **It cannot tell a real name from an invented one.** That part is a rule in
  AGENTS.md, and the hook is the floor under it, not a replacement for it.

### What leaves the system names nobody

- **The shortlist carries candidate ids and CV links, never names.** A digest
  whose body names somebody — in the prose, or inside a link built from a file
  stored under the name it arrived with — is refused rather than sent.
- **Identity lives behind the CV link**, where the folder's own sharing decides
  who may learn it. A link is resolved against that sharing every time, so
  access withdrawn is actually withdrawn; an attachment never is.
- **No tool takes a recipient.** The only outbound tool reaches the configured
  operator addresses and has no argument that could point it anywhere else.
- **Every recipient is checked against `allow_domains`** before the first
  message is sent, so a blocked address means nobody is mailed rather than
  half of them.
- **Dry run is on until you turn it off**, so the first run of a
  misconfiguration logs instead of sending.

### The sending identity cannot read a single CV

`talanton fetch` reads the apply mailbox over IMAP and **cannot send**: no SMTP
path, and no import of the module that has one. Sending is a separate account
with no IMAP access at all. Misusing either one gets you half of what a single
identity would have given you.

### Credentials

- **Never in the repository.** The mailbox and sending passwords come from the
  environment or Google Secret Manager, resolved at send time; the committed
  TOML holds settings only, which is what makes it safe to review in a pull
  request.
- **Never a service-account key file**, anywhere, for anything. Cloud access is
  application default credentials or an attached service account.
- **Never printed or logged.** An SMTP refusal is reported as why the login was
  refused, without the password.
- **gitleaks runs as a hook on every commit.**

### A CV is untrusted text, and so is what a model wrote about it

A CV is written by a stranger who may know a screener will read it. Its text is
fenced before it reaches a model, with a per-call nonce, and any existing fence
markers in it are stripped so they cannot be forged. The screener's own prose
is fenced again on the way out of the tools, because the agent that can
delegate reads it. A screener holds no tools, and a knockout is enforced in
code before the agent sees anybody, so a candidate filtered out cannot be
written about even if a CV asks for it.

## If candidate data reaches the repository

This is not a credential leak and the remediation is not the same. A password
can be rotated; a person's CV cannot.

1. Treat the history as disclosed. Removing the file from `main` leaves it in
   every clone, fork and cached view.
2. Tell the repository owner before doing anything else, so the decision about
   the applicant — who has to be told, and by whom — is made by a person.
3. Rewriting public history is a last resort and does not undo disclosure.
   Decide it deliberately, not as a reflex.
