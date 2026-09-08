---
description: Run the recruitment cycle by hand, one stage at a time, and report what happened
---

Run the cycle manually and show your work. Two stages do the actual work, and
neither needs a mailbox.

```bash
export TALANTON_CONFIG=./talanton.toml   # or hiring/talanton.toml
```

## 0. Look before you touch

```bash
talanton check
talanton status
```

`check` must pass first. `status` reads the two locations directly — no model,
no mailbox, no cost — and tells you how many CVs are waiting and who has
already been assessed.

## 1. Get CVs into the CVs location

Either someone drops them in, or:

```bash
talanton inbox     # what is unread. marks nothing, sends nothing
talanton fetch     # mailbox -> CVs folder
```

`fetch` cannot send: no SMTP path, and no import path to one — a test walks the
import graph to keep it that way. Nothing a candidate writes can provoke a
reply, however it is phrased. It makes no model call either.

Report what arrived, and anything that could not be read.

## 2. Assess

```bash
talanton next <opening>
#   read the CV it prints, write the assessment JSON, then:
talanton record <cv> --opening <n> --from a.json
#   repeat until it says nothing is waiting
```

You are the model here. `talanton assess` exists for an unattended deployment
and starts a second agent on Vertex to do what you have just done — do not
reach for it.

Every CV without an assessment is read against the position's rubric, and the
assessment is written to the assessments location. **An assessment that is not
saved does not exist** — if the output does not say assessments were saved,
that is the bug; check `talanton status` before going on.

Two things to watch for and report honestly:

- **Unreadable CVs are not zeros.** A scanned PDF with no text layer must be
  reported by filename, never scored. If you see one scored, stop.
- **Knockout failures are filtered here, in code.** Check who:

```bash
talanton status <role>
```

Read any one of them in full with:

```bash
talanton show <opening> <candidate-id>
```

If the filter caught someone it should not have, that is a rubric problem. Say
so, name the id, and use `/review-filter`. Do not route around the filter.

## 3. Shortlist

```bash
talanton shortlist <role>
```

Sends the operator who is worth reading — **by candidate id, with a link to
each CV, never a name.** Identity lives behind the link, where folder
permissions decide who may learn it. A summary containing a name is refused by
the tool, not quietly sent.

If nobody clears the bar, nothing is sent and it says so. A quiet week is a
useful result, not a failure — do not lower the bar to produce a shortlist.

## 4. Report

How many CVs arrived, how many were assessed, how many were unreadable and
which files, how many the filter held back and on what, and who was surfaced.

Nothing here can contact a candidate, and you must not try to. If a CV leaves a
question open, put the question in the shortlist so a person can ask it.
