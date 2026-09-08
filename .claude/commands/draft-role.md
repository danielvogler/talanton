---
description: Interview the operator about an open role and write its position file
---

Write a new position file. Do not start from a template dump — interview first,
draft second.

One YAML holds the ad copy, the knockouts and the rubric together, because they
are the same decision written three ways. Change what the role requires and the
ad, the screening standard and the questions candidates get asked all move with
it. That is the point of the format, so fill in all three or none.

## 1. Interview

Ask only what you cannot infer, a few questions at a time. You need:

- What the person will actually do in their first six months. Push for
  specifics; "work on our AI platform" is not something you can screen against.
- What makes a candidate an obvious no, and what makes one an obvious yes.
- Seniority, salary band, employment type, workplace (onsite / hybrid /
  remote), and for remote, which countries are acceptable.
- Where applications should arrive. Each position gets its own address, or one
  address with a plus tag — that is how an application is routed to the right
  role without anyone setting an environment variable.
- When the role closes.

If the operator resists naming a salary band, say that omitting it costs reach —
indexers rank salaried postings higher and candidates filter on it — then
respect their answer.

## 2. Write it

Create `<store>/openings/<opening>-<id>.yaml`, modelled on
[`example/openings/101-ai-engineer.yaml`](../../example/openings/101-ai-engineer.yaml).
The `id` is lowercase-hyphenated and is never reused for a different role.

Write `pitch` as prose for the candidate you want, not a list of technologies.
Concrete detail: team size, who they report to, what the first project is.
Generic postings attract generic applicants.

Keep `requirements` short and testable. Every line must be something you could
later check against a CV. If you cannot check it, it belongs in the pitch or
nowhere.

## 3. Write the rubric, and be careful with knockouts

The rubric must be specific enough that two readers would score the same CV
within a point of each other. For each dimension: what it measures, what a 2, a
5 and an 8 look like concretely, and its weight.

**A knockout removes a person from the process entirely, in code.** A candidate
who fails one is filtered out of every listing the agent can see and never
reaches a digest — that is enforced in `screening.py`, not left to a prompt. So:

- Only write a knockout the operator has explicitly asked for.
- Only write one that is genuinely pass/fail and could never be compensated for.
- Prefer a scored dimension. Say so if you are choosing one over a knockout.

`screening.min_score` is the other filter and it is opt-in. Leave it out unless
the operator asks; a floor set too high discards people quietly.

Add `must_not_influence`: name, gender, nationality beyond the right to work,
age, photograph, university prestige as a proxy for ability. This is not
decoration; it is what the rubric is for.

## 4. Validate and show the ads

```bash
talanton positions
talanton ads <id>
```

Fix every error. Read the board `setup` notes aloud the first time a board is
used, and flag any `!!` length warning — those mean a human has to decide what
to cut. Nothing here posts anything anywhere; pasting is the operator's job.

Report what you wrote, which knockouts you chose and why, and what still needs
their answer.
