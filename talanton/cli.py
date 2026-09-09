"""The command line, and the way a coding agent drives this by hand.

    talanton init [--dir D]     scaffold a hiring setup in this repository
    talanton secret <side>      put a mailbox app password in Secret Manager
    talanton check              is the configuration sane
    talanton positions          list and validate the open positions
    talanton ads <opening>      paste-ready board copy, to stdout
    talanton status [opening]   every opening and where each one stands
    talanton show <opening> <candidate>
                                   one assessment, in full, readable

  Driven by you, the coding agent — no model configured, nothing billed:
    talanton rubric <opening>   the screening standard, as the screener gets it
    talanton next <opening>     the next unassessed CV, fenced, with the rubric
    talanton record <cv>        save the assessment you just made
    talanton send <opening>     send the shortlist you just wrote

  Driven by a deployed agent — these call a model on Vertex:
    talanton assess <opening>   assess the CVs that have no assessment yet
    talanton shortlist <opening>  hand the operator who is worth reading
    talanton cycle <opening>    fetch if configured, then both of the above

    talanton fetch              mailbox -> CVs location. CANNOT SEND
    talanton inbox              what is unread, touching nothing
    talanton drive-folder <p>   a Drive folder's id by path, --create to make it

The core is `assess` and `shortlist`, and neither needs a mailbox. Put CVs in
the CVs location by any means — drop them in a folder, or let `fetch` pull them
out of email — and the rest is the same either way.
"""

import argparse
import sys
from pathlib import Path

from . import config, locations, positions

EXIT_FAILURE = 1
VERTEX_VARS = ("GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION")


def _print(ok: bool, message: str) -> bool:
    print(f"{'ok  ' if ok else 'FAIL'}  {message}")
    return ok


def check_locations() -> bool:
    """Both locations resolve. A local one is created; a remote one is named."""
    active = config.current()
    ok = True
    for label, spec in (("cvs", active.cvs), ("assessments", active.assessments)):
        try:
            built = locations.build(spec, active.store)
            # Building only reads the config. Reaching it is the question worth
            # answering here, because an unreachable location reads as empty.
            built.verify()
            ok = _print(True, f"{label}: {built}") and ok
        except locations.LocationError as exc:
            ok = _print(False, f"{label}: {exc}")
    return ok


def check_config(configured: bool) -> bool:
    """The configuration loads and says who may be mailed."""
    try:
        active = config.current()
    except config.ConfigError as exc:
        return _print(False, f"config: {exc}")

    if not configured:
        print("note  no talanton.toml found; checking defaults, not a deployment")
        return _print(True, "defaults load")

    ok = _print(True, f"config loads; working area {active.store}")
    if not active.inbound.user:
        print("note  no apply mailbox — `fetch` is unavailable; drop CVs in the folder instead")
    else:
        _report_password("inbound", active.inbound, active.screening.project)
    if active.outbound.user:
        _report_password("outbound", active.outbound, active.screening.project)
    if not active.outbound.operators:
        print("note  no operator address — `shortlist` cannot email; read it with `status` instead")
    if active.inbound.user and active.inbound.user == active.outbound.user:
        print(
            "warn  the sending identity is the apply mailbox. Use a separate account, "
            "so what sends cannot read a CV"
        )
    return ok and _check_sending(active)


def _outbound_password_reachable() -> bool:
    """Whether `outbound.send` would find a password.

    Asks the same resolver `send` uses, so this cannot drift away from it: the
    environment, then Secret Manager. A secret nobody may read is unreachable,
    which is the answer, not an error.
    """
    from . import outbound as outbound_module
    from . import secrets

    try:
        return bool(outbound_module.password())
    except secrets.SecretError as exc:
        print(f"note  outbound password: {exc}")
        return False


def _check_login(outbound) -> bool:
    """Whether Google actually accepts the sending password.

    Reading the secret proves the IAM grant works and nothing else. This is the
    only step that answers the question `check` is asked, and it is worth the
    round trip: the alternative is finding out after a run has assessed
    everybody and has a shortlist it cannot deliver.
    """
    from . import outbound as outbound_module

    refused = outbound_module.probe()
    if refused:
        return _print(False, f"the sending account cannot log in.\n      {refused}")
    return _print(True, f"{outbound_module.login_identity()} can log in to {outbound.smtp_server}")


def _check_sending(active: config.Config) -> bool:
    """Whether a shortlist could actually be delivered.

    Every one of these fails at send time otherwise — which is after a whole
    assessment run has been paid for, and is the wrong moment to find out.
    """
    outbound = active.outbound
    if outbound.dry_run:
        print("note  dry run is on; mail is logged, not sent")
        return True

    print("warn  dry run is OFF — the shortlist will really be sent")
    # Named, not counted. The allowlist matches a domain, so a typo at a
    # permitted domain passes every check here and is still somebody who gets
    # candidate links. The only thing that catches it is a person reading the
    # addresses before the first real run.
    for address in outbound.operators:
        print(f"      shortlists will go to {address} — read that address, not the count")
    ok = True

    if not _outbound_password_reachable():
        ok = _print(
            False,
            "dry run is off but no sending password is reachable: set $TALANTON_OUTBOUND_PASSWORD, "
            "or mail.outbound.password_secret and a grant to read it. Sending will fail.",
        )
    else:
        ok = _check_login(outbound) and ok

    if not outbound.allow_domains:
        print(
            "warn  mail.outbound.allow_domains is empty, so every recipient is permitted. "
            "The documented ceiling is only a ceiling once it lists a domain."
        )

    unreachable = [
        address
        for address in outbound.operators
        if outbound.allow_domains and address.rsplit("@", 1)[-1] not in outbound.allow_domains
    ]
    if unreachable:
        ok = _print(
            False,
            f"the allowlist blocks the operator(s) it is meant to reach: {', '.join(unreachable)}. "
            f"Add their domain to mail.outbound.allow_domains ({', '.join(outbound.allow_domains)}).",
        )
    return ok


def check_model() -> bool:
    """Whether a model is configured, which most setups never need.

    A coding agent driving `next` and `record` is the model, so no project and
    no model id are required. This only matters for an unattended deployment.
    Reporting it as something missing would send people to configure a cloud
    they have no use for.
    """
    import os

    if [v for v in VERTEX_VARS if not os.environ.get(v)]:
        print(
            "note  no model configured, which is normal: `next` and `record` let a coding "
            "agent do the assessing.\n      Only an unattended deployment needs one."
        )
        return True
    print(
        f"ok    Vertex: {os.environ['GOOGLE_CLOUD_PROJECT']} in "
        f"{os.environ['GOOGLE_CLOUD_LOCATION']}, model {config.current().screening.model}"
    )
    return True


def _report_password(side: str, section, project: str) -> None:
    """Says where a mailbox password comes from, and whether you can read it.

    Never prints the value, and a denial is reported as information rather than
    a failure: being unable to read it is a legitimate state for someone who is
    not meant to run the pipeline.
    """
    import os

    from . import secrets

    env = "TALANTON_INBOUND_PASSWORD" if side == "inbound" else "TALANTON_OUTBOUND_PASSWORD"
    if section.password or os.environ.get(env):
        print(f"note  {side} password from the environment")
        return
    if not section.password_secret:
        print(f"note  {side} has no password configured; set ${env} or mail.{side}.password_secret")
        return

    try:
        secrets.read(section.password_secret, project)
    except secrets.SecretError as exc:
        print(f"note  {side} password: {exc}")
        return
    print(f"ok    {side} password readable from Secret Manager ({section.password_secret})")


def check_positions() -> bool:
    """Every position parses, and no two openings share a number."""
    files = positions.all_roles()
    if not files:
        return _print(True, "no openings yet — write one with /draft-role")

    for name in files:
        try:
            positions.load(name)
        except (positions.PositionError, FileNotFoundError) as exc:
            return _print(False, f"position {name}: {exc}")

    numbers = [str(p["opening"]) for p in positions.every()]
    clashes = sorted({n for n in numbers if numbers.count(n) > 1})
    if clashes:
        return _print(False, f"two openings share the number(s) {', '.join(clashes)}. Numbers must be unique.")

    return _print(True, f"{len(files)} opening(s): {', '.join(positions.slug(p) for p in positions.every())}")


CONFIG_TEMPLATE = """# Written by `talanton init`. Settings live here and are committed.
# Secrets never do — every password comes from .env beside this file.

[company]
name = "{company}"
# Reaches the agent's own instructions. One factual clause, not marketing.
description = "a company"

[store]
# openings/ lives here, and relative locations below resolve against this
# file's directory, so the
# commands work from anywhere in the repository.
path = "."

[storage.cvs]
backend = "local"           # local | gdrive | gcs
path = "cvs"

[storage.assessments]
backend = "local"
path = "assessments"

[screening]
# Where the model is served. Named explicitly so a run cannot land on whatever
# gcloud last pointed at. Not needed if a coding agent does the assessing.
# project  = "your-project"
# location = "global"
model = "gemini-3.8-flash"

# Optional. Reading the apply mailbox — this side cannot send.
# [mail.inbound]
# user = "apply@{domain}"

# Optional. Sending the shortlist — a DIFFERENT account, with no access to the
# mailbox above, so if it were misused it could not read a CV.
# [mail.outbound]
# user = "hiring-bot@{domain}"
# If the address above is an ALIAS, name the account it belongs to. An alias
# cannot authenticate, and Google refuses it with the same 535 it gives a wrong
# password, so this looks like a bad app password for as long as you let it.
# login_user = "bot@{domain}"
# operators = ["you@{domain}"]
# allow_domains = ["{domain}"]
# dry_run = true
"""

ENV_TEMPLATE = """# Secrets only. Gitignored — keep it that way.
# App passwords, not account passwords. Only needed if you use a mailbox.
#
# Paste the app password exactly as Google shows it — the spaces in
# "abcd efgh ijkl mnop" are display only and are stripped for you.
TALANTON_INBOUND_PASSWORD=
TALANTON_OUTBOUND_PASSWORD=
"""

GITIGNORE_BLOCK = """
# talanton: candidate data and secrets never go in git.
{directory}/cvs/
{directory}/assessments/
{directory}/.env
"""


def cmd_init(args: argparse.Namespace) -> int:
    """Scaffold a hiring setup, without overwriting anything that exists.

    Everything it writes is inert: no mailbox, no cloud, dry run implied. The
    point is that the shape is right — candidate data gitignored before the
    first CV arrives, rather than after.
    """
    directory = Path(args.dir)
    company = args.company or Path.cwd().name
    domain = args.domain or "example.com"

    created, skipped = [], []
    for relative, content in (
        ("talanton.toml", CONFIG_TEMPLATE.format(company=company, domain=domain)),
        (".env", ENV_TEMPLATE),
    ):
        target = directory / relative
        if target.exists():
            skipped.append(str(target))
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        created.append(str(target))

    for subdirectory in ("openings", "cvs", "assessments"):
        (directory / subdirectory).mkdir(parents=True, exist_ok=True)

    ignored = _ensure_gitignored(directory)

    for path in created:
        print(f"ok    wrote {path}")
    for path in skipped:
        print(f"note  {path} exists already; left alone")
    print(f"ok    {directory}/openings, cvs, assessments")
    print(f"{'ok  ' if ignored else 'note'}  .gitignore {'updated' if ignored else 'already covers the data'}")

    print(f"""
Next:
  1. Fill in {directory}/talanton.toml — the company description at least.
  2. export TALANTON_CONFIG={directory}/talanton.toml
  3. talanton check
  4. Write the first role, then put CVs in {directory}/cvs/ and assess them.

Nothing here reaches a mailbox or the cloud yet, and no candidate data is
tracked by git.""")
    return 0


def _ensure_gitignored(directory: Path) -> bool:
    """Adds the data paths to .gitignore. Returns whether it changed anything."""
    block = GITIGNORE_BLOCK.format(directory=directory.as_posix().rstrip("/"))
    gitignore = Path(".gitignore")
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""

    missing = [
        line
        for line in block.strip().splitlines()
        if line and not line.startswith("#") and line not in existing
    ]
    if not missing:
        return False

    gitignore.write_text(existing.rstrip("\n") + "\n" + block, encoding="utf-8")
    return True


def cmd_secret(args: argparse.Namespace) -> int:
    """Put one mailbox app password into Secret Manager.

    The password is read from stdin and never echoed, never logged, and never
    written to disk. After this, whether a colleague can run the pipeline is an
    IAM decision on the secret rather than whether anyone sent them a password.
    """
    import getpass

    from . import secrets

    project = args.project or config.current().screening.project
    if not project:
        print(f"FAIL  {_no_project()}", file=sys.stderr)
        return EXIT_FAILURE

    name = args.name or f"talanton-{args.side}"
    print(f"Creating {name} in {project}.")
    print("Paste the Google app password. It is not echoed, and the spaces are stripped.")
    value = getpass.getpass("app password: ") if sys.stdin.isatty() else sys.stdin.read()

    if not "".join(value.split()):
        print("FAIL  nothing was entered.", file=sys.stderr)
        return EXIT_FAILURE

    try:
        version = secrets.create(name, project, value)
    except secrets.SecretError as exc:
        print(f"FAIL  {exc}", file=sys.stderr)
        return EXIT_FAILURE

    print(f"\nok    added {version}\n")
    print("Put this in talanton.toml — the name, never the value:\n")
    print(f"[mail.{args.side}]")
    print(f'password_secret = "{name}"\n')
    print("Then anyone who should run the pipeline needs read access to it:\n")
    print(secrets.grant_command(name, project))
    print("\nAnyone without that grant is stopped by Google. Do not send them the password.")
    return 0


def _no_project() -> str:
    """Why there is no project, which is usually that no config was found at all.

    Saying "set [screening] project" to someone whose config is simply not being
    read sends them to edit a file that was never opened.
    """
    if config.find() is None:
        return (
            "no config file found, so there is no project to create the secret in.\n"
            "      talanton looks for ./talanton.toml, or $TALANTON_CONFIG. Point at yours:\n\n"
            "        talanton --config path/to/talanton.toml secret ...\n"
            "        export TALANTON_CONFIG=path/to/talanton.toml\n\n"
            "      Or pass --project to skip the config entirely."
        )
    return f"the config at {config.find()} sets no [screening] project. Add one, or pass --project."


def cmd_check(args: argparse.Namespace) -> int:
    configured = bool(args.config or config.find())
    checks = [check_config(configured), check_locations(), check_model(), check_positions()]
    return 0 if all(checks) else EXIT_FAILURE


def cmd_positions(args: argparse.Namespace) -> int:
    return 0 if check_positions() else EXIT_FAILURE


def cmd_ads(args: argparse.Namespace) -> int:
    try:
        print(positions.ads(positions.resolve(args.opening)))
    except (FileNotFoundError, positions.PositionError, positions.AmbiguousOpeningError) as exc:
        print(f"FAIL  {exc}", file=sys.stderr)
        return EXIT_FAILURE
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Every opening, or one, read straight off the locations.

    No mailbox, no model, no cost. Listed by number, because five postings can
    share a title and only the number says which is which.
    """
    from . import store, tools

    wanted = [positions.resolve(args.opening)] if args.opening else positions.every()
    if not wanted:
        print("no openings yet — write one with /draft-role")
        return 0

    for position in wanted:
        slug = positions.slug(position)
        waiting = tools.list_new_cvs(slug)
        candidates = tools.list_candidates(slug)["candidates"]
        excluded = tools.list_excluded(slug)["excluded"]

        print(f"\nopening {position['opening']} — {position['title']}, closes {position['closes']}")
        print(
            f"  {len(store.list_cvs(slug))} CV(s), {waiting['count']} unassessed, "
            f"{len(candidates)} shortlistable, {len(excluded)} held back"
        )
        for row in waiting["waiting"]:
            print(f"      ?   {row['candidate']}  {row['cv']}")
        for row in candidates:
            score = f"{row['score']:.1f}" if isinstance(row["score"], int | float) else "  — "
            gaps = f"  gaps: {','.join(row['gaps'])}" if row["gaps"] else ""
            print(f"  {score}  {row['candidate']}{gaps}")
        for row in excluded:
            print(f"      ·   {row['candidate']}  held back: {', '.join(row['reasons'])}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    """One assessment in full, for a person to read.

    This is where a name appears: you are looking at the record on your own
    machine, having opened it deliberately. The shortlist that travels by email
    still carries ids only.
    """
    from . import screening, store

    position = positions.resolve(args.opening)
    slug = positions.slug(position)
    assessment = store.assessment(args.candidate, slug)
    if not assessment:
        print(f"FAIL  no assessment for {args.candidate!r} in opening {slug}", file=sys.stderr)
        return EXIT_FAILURE

    facts = assessment.get("facts") or {}
    held = screening.exclusions(assessment, position)

    print(f"{args.candidate}   {facts.get('name') or 'name not found in the CV'}")
    print(f"  opening     {position['opening']} — {position['title']}")
    print(f"  cv          {assessment.get('cv', '')}")
    print(f"  open it     {assessment.get('cv_uri', '')}")
    print(f"  assessed    {assessment.get('assessed_on', '')}")

    score = assessment.get("overall")
    print(f"\n  overall     {score if score is not None else '—'}")
    for dimension, value in (assessment.get("dimensions") or {}).items():
        print(f"    {dimension:<24} {value}")

    print("\n  facts")
    for key, value in facts.items():
        print(f"    {key:<24} {value}")

    if knockouts := assessment.get("knockouts"):
        print("\n  knockouts")
        for key, verdict in knockouts.items():
            print(f"    {key:<24} {verdict}")

    if assessment.get("justification"):
        print(f"\n  {assessment['justification']}")
    for probe in assessment.get("probe") or []:
        print(f"    ask: {probe}")
    if assessment.get("flags"):
        print(f"\n  flags       {', '.join(assessment['flags'])}")

    if held:
        print(f"\n  HELD BACK   {', '.join(held)}")
        print("              Not in any shortlist. Fix the rubric if this is wrong;")
        print("              do not route around the filter.")
    return 0


# --------------------------------------------------------------------------
# Driven by a coding agent. You are the model, so none of this calls one.
# --------------------------------------------------------------------------


def cmd_rubric(args: argparse.Namespace) -> int:
    """The screening standard, exactly as the screener agent would receive it."""
    print(positions.rubric_text(positions.resolve(args.opening)))
    return 0


def cmd_next(args: argparse.Namespace) -> int:
    """Everything needed to assess one CV, for you to assess it yourself.

    Emits the rubric, the CV fenced as untrusted text, and the schema to return
    — the same one the deployed screener has enforced on it.
    Exits 0 with a note when the queue is empty, so a loop can stop on it.
    """
    from . import agent, assessment, tools

    slug = positions.slug(positions.resolve(args.opening))
    waiting = tools.list_new_cvs(slug)["waiting"]
    if not waiting:
        print(f"nothing waiting for opening {slug}")
        return 0

    row = waiting[0]
    text = tools.get_cv_text(slug, row["cv"])

    print(f"=== opening {slug}: {row['cv']}  ({row['candidate']})   {len(waiting)} waiting ===\n")
    if text.get("unreadable"):
        print(f"UNREADABLE: {text['unreadable']}\n")
        print("Do not score this. Record nothing, and tell the operator which file it was.")
        return 0
    if not text.get("cv"):
        print(f"ERROR: {text.get('error')}")
        return EXIT_FAILURE

    print(positions.rubric_text(positions.resolve(args.opening)))
    print("\n=== the CV ===\n")
    print(text["cv"])
    print("\n=== what to do ===\n")
    print(agent.SCREENER_INSTRUCTION)
    print("\n=== the shape to return, and to hand to `record` ===\n")
    print(assessment.contract())
    print(f"\nThen save it:\n  talanton record {row['cv']} --opening {args.opening} --from assessment.json")
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    """Save an assessment you produced. The same filter runs as for an agent."""
    import json

    from . import tools

    raw = sys.stdin.read() if args.__dict__["from"] == "-" else Path(args.__dict__["from"]).read_text("utf-8")
    from pydantic import ValidationError

    from .assessment import Assessment

    try:
        assessment = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"FAIL  that is not valid JSON: {exc}", file=sys.stderr)
        return EXIT_FAILURE

    # The deployed screener has this shape enforced by the API. Writing the
    # JSON by hand is no way around it, any more than it is a way around the
    # knockout filter below.
    try:
        Assessment.model_validate(assessment)
    except ValidationError as exc:
        print(f"FAIL  that is not an assessment:\n{exc}", file=sys.stderr)
        return EXIT_FAILURE

    result = tools.save_assessment(args.opening, args.cv, assessment)
    if not result["saved"]:
        print(f"FAIL  {result.get('reason')}", file=sys.stderr)
        return EXIT_FAILURE

    print(f"ok    saved {result['candidate']} -> {result['written_to']}")
    if result["excluded"]:
        print(f"note  held back by the filter: {', '.join(result['reasons'])}")
        print("      They will not appear in any shortlist. That is the filter working.")
    return 0


def cmd_send(args: argparse.Namespace) -> int:
    """Send a shortlist you wrote yourself, through the same guards.

    The name check and the CV links are applied here exactly as they are for
    the agent — writing the summary yourself does not get you past them.
    """
    from . import tools

    summary = sys.stdin.read() if args.summary == "-" else args.summary
    candidates = [c.strip() for c in args.candidates.split(",") if c.strip()]

    result = tools.send_digest(args.opening, summary.strip(), candidates)
    if not result["sent"]:
        print(f"FAIL  {result['reason']}", file=sys.stderr)
        return EXIT_FAILURE

    print(f"ok    sent to {', '.join(result['to'])}")
    if result["linked"]:
        print(f"      linked: {', '.join(result['linked'])}")
    for refusal in result["refused"]:
        print(f"note  {refusal['candidate']}: {refusal['reason']}")
    return 0


def cmd_inbox(args: argparse.Namespace) -> int:
    """Look, touch nothing. Nothing is marked read and no agent runs."""
    from . import inbound

    messages = inbound.peek()
    print(f"{len(messages)} unread")
    for message in messages:
        print(f"  {message['sender']:<34} {message['subject'][:60]}")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    from . import inbound

    written = inbound.fetch()
    print(f"fetched {len(written)} CV(s)" + ("" if not written else ":"))
    for name in written:
        print(f"  {name}")
    return 0


def cmd_assess(args: argparse.Namespace) -> int:
    from . import run

    print(run.assess(args.opening, rescreen=args.rescreen))
    return 0


def cmd_shortlist(args: argparse.Namespace) -> int:
    from . import run

    print(run.shortlist(args.opening))
    return 0


def cmd_cycle(args: argparse.Namespace) -> int:
    from . import run

    if args.watch:
        run.watch(args.opening)
        return 0
    for stage, said in run.cycle(args.opening).items():
        print(f"\n=== {stage} ===\n{said}")
    return 0


def cmd_drive_folder(args: argparse.Namespace) -> int:
    """Turn a Drive path into the id the config wants."""
    from . import drive

    try:
        folder_id = drive.resolve_folder(
            drive.service(),
            args.path,
            create=args.create,
            root=args.__dict__["in"] or drive.ROOT,
            force=args.force,
        )
    except locations.LocationError as exc:
        print(f"FAIL  {exc}", file=sys.stderr)
        return EXIT_FAILURE

    print(f"ok    {args.path!r} is {folder_id}\n")
    print("Put this in talanton.toml:\n")
    print(f"[storage.{args.__dict__['for']}]")
    print('backend = "gdrive"')
    print(f'folder_id = "{folder_id}"')

    if args.__dict__["for"] == "cvs":
        print(
            "\nAssessments need their own folder — they carry names and judgements,\n"
            "and often belong to a smaller group than the CVs do:\n\n"
            f'  talanton drive-folder "{args.path.rstrip("/")}/../assessments" '
            "--create --for assessments"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="talanton", description=__doc__.splitlines()[0])
    parser.add_argument("--config", help="Path to talanton.toml. Discovered if omitted.")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="scaffold a hiring setup in this repository")
    init.add_argument("--dir", default="hiring", help="where it goes (default: hiring)")
    init.add_argument("--company", help="company name (default: this directory's name)")
    init.add_argument("--domain", help="your email domain, for the commented-out mail section")
    init.set_defaults(func=cmd_init)

    secret = sub.add_parser("secret", help="put a mailbox app password in Secret Manager")
    secret.add_argument("side", choices=("inbound", "outbound"), help="which mailbox")
    secret.add_argument("--project", default="", help="GCP project (default: [screening] project)")
    secret.add_argument("--name", default="", help="secret name (default: talanton-<side>)")
    secret.set_defaults(func=cmd_secret)

    sub.add_parser("check", help="validate the configuration and the locations").set_defaults(func=cmd_check)
    sub.add_parser("positions", help="list and validate the open positions").set_defaults(func=cmd_positions)
    sub.add_parser("inbox", help="list unread mail, touching nothing").set_defaults(func=cmd_inbox)
    sub.add_parser("fetch", help="mailbox -> CVs location; cannot send").set_defaults(func=cmd_fetch)

    ads = sub.add_parser("ads", help="print paste-ready board copy for one role")
    ads.add_argument("opening", help='an opening number, e.g. "123"')
    ads.set_defaults(func=cmd_ads)

    status = sub.add_parser("status", help="what is in each location")
    status.add_argument("opening", nargs="?", help="an opening number; omit for all")
    status.set_defaults(func=cmd_status)

    show = sub.add_parser("show", help="one assessment, in full")
    show.add_argument("opening", help="the opening number")
    show.add_argument("candidate", help="a candidate id, as printed by status")
    show.set_defaults(func=cmd_show)

    rubric = sub.add_parser("rubric", help="print the screening standard for a role")
    rubric.add_argument("opening")
    rubric.set_defaults(func=cmd_rubric)

    nxt = sub.add_parser("next", help="the next unassessed CV, for you to assess yourself")
    nxt.add_argument("opening")
    nxt.set_defaults(func=cmd_next)

    record = sub.add_parser("record", help="save an assessment you produced")
    record.add_argument("cv", help="the CV filename, as printed by next")
    record.add_argument("--opening", required=True, help="the opening number")
    record.add_argument("--from", required=True, help="a JSON file, or - for stdin")
    record.set_defaults(func=cmd_record)

    send = sub.add_parser("send", help="send a shortlist you wrote yourself")
    send.add_argument("opening")
    send.add_argument("--candidates", required=True, help="comma-separated candidate ids")
    send.add_argument("--summary", required=True, help="the text, or - for stdin")
    send.set_defaults(func=cmd_send)

    assess = sub.add_parser("assess", help="assess the CVs that have no assessment yet (calls a model)")
    assess.add_argument("opening")
    assess.add_argument("--rescreen", action="store_true", help="re-assess everyone, after a rubric change")
    assess.set_defaults(func=cmd_assess)

    shortlist = sub.add_parser("shortlist", help="hand the operator who is worth reading")
    shortlist.add_argument("opening")
    shortlist.set_defaults(func=cmd_shortlist)

    cycle = sub.add_parser("cycle", help="fetch if configured, then assess and shortlist")
    cycle.add_argument("opening")
    cycle.add_argument("--watch", action="store_true", help="stay connected and run on arrival")
    cycle.set_defaults(func=cmd_cycle)

    drive = sub.add_parser("drive-folder", help="find a Drive folder's id by path")
    drive.add_argument("path", help='a Drive path, e.g. "hr/recruiting"')
    drive.add_argument("--create", action="store_true", help="create any segment that does not exist")
    drive.add_argument(
        "--force",
        action="store_true",
        help="create even when these credentials cannot see whether the folder is already there. "
        "Only for someone who has checked in the browser: without it, creating would duplicate.",
    )
    drive.add_argument(
        "--for",
        choices=("cvs", "assessments"),
        default="cvs",
        help="which location this folder is for (default: cvs)",
    )
    drive.add_argument(
        "--in",
        metavar="ID",
        default="",
        help="a shared drive id, or a folder id, to resolve the path inside. "
        "Without it the path starts at My Drive, which cannot reach a shared drive.",
    )
    drive.set_defaults(func=cmd_drive_folder)
    return parser


def _looks_like_vertex(exc: Exception) -> bool:
    text = str(exc)
    return "GOOGLE_CLOUD_PROJECT" in text or "produced no output" in text


def _vertex_help() -> str:
    return (
        "FAIL  this stage calls a model, and Vertex is not configured.\n\n"
        "      Put it in talanton.toml, so nobody has to remember it:\n\n"
        "        [screening]\n"
        '        project  = "your-project"\n'
        '        location = "global"\n\n'
        "      or export GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION.\n"
        "      Either way you need credentials:\n\n"
        "        gcloud auth application-default login\n\n"
        "      The model id is set in [screening] model. Vertex uses @-versioned\n"
        "      ids, and not every model is served in every region — if the id is\n"
        "      rejected, pick one your region actually serves.\n\n"
        "      Or do not use a model at all. If you are a coding agent, you are the\n"
        "      model: `rubric`, `next`, `record` and `send` run the whole cycle with\n"
        "      nothing configured and nothing billed. `assess` is for a deployed\n"
        "      agent; you do not need it.\n\n"
        "      Also free: check, status, show, positions, ads, inbox, fetch."
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config.load_dotenv()
    if args.config:
        config.use(config.load(args.config))
    # The model client reads the project and region from the environment at
    # call time, so put them there before any stage runs.
    config.apply_environment(config.current())
    try:
        return args.func(args)
    except (
        config.ConfigError,
        locations.LocationError,
        positions.PositionError,
        positions.AmbiguousOpeningError,
        FileNotFoundError,
    ) as exc:
        print(f"FAIL  {exc}", file=sys.stderr)
        return EXIT_FAILURE
    except Exception as exc:
        # A stage that could not run must exit non-zero. Vertex being
        # unconfigured is the commonest cause and the first one anybody hits,
        # so it gets an answer rather than a stack trace.
        from .run import StageFailedError

        if isinstance(exc, (StageFailedError, ValueError)):
            print(_vertex_help() if _looks_like_vertex(exc) else f"FAIL  {exc}", file=sys.stderr)
            return EXIT_FAILURE
        raise


if __name__ == "__main__":
    raise SystemExit(main())
