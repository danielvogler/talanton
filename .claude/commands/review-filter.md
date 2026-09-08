---
description: Audit who the knockout filter removed, and propose a rubric change if it was wrong
---

The filter removes people before a human sees them. That is the whole value of
it and also the whole risk, so it gets audited deliberately rather than
whenever someone remembers.

## 1. See who it caught

```bash
talanton status <role>
```

Every filtered candidate is listed with the reason. If nobody was filtered, say
so and stop.

## 2. For each one, decide what actually failed

Read the assessment's `facts` block against the CV. This is why facts are
recorded separately from scores.

- **Reading failure** — the facts are wrong. The assessment recorded
  `work_permit: fail` because it read a student visa as no right to work. The
  rubric is fine; the extraction is not. Fix how the knockout is worded so it is
  unambiguous, and re-screen. Changing the rubric here would be compensating for
  a parsing bug by distorting the criteria.
- **Rubric failure** — the facts are right and the exclusion is still wrong. The
  knockout is drawn in the wrong place.

Say which one you concluded, and why. If you cannot tell, ask.

## 3. Show the cost before proposing anything

A knockout cannot be compensated for by strength elsewhere, so state plainly
what it removed:

> the `academic-only` knockout excluded 4 assessed candidates, including one
> scoring 8.5

That sentence is what stops a bad rubric change. Then propose the edit as a diff
a person can argue with — thresholds and worked examples, not weights nudged by
a tenth.

## 4. On approval

Bump `version` in the position file, commit with the candidates that motivated
the change named in the message, and re-screen the pool so the new standard
applies to everyone rather than only to whoever arrives next.

Report who moved. "Two previously filtered now clear it" is the payoff for
keeping records, and it means an early miscalibration is recoverable rather
than a set of people you silently lost.

Never adjust a score or a threshold outside this path, and never feed past
decisions into the screening prompt as examples — that is a model quietly
learning preferences nobody wrote down, and it destroys both the audit trail
and the claim that the rubric was applied uniformly.
