# Engineer Guide — IFC Compliance Checker Admin System

This document is the knowledge base for the built-in help assistant shown
to engineers on the admin panel. It is chunked by "## " section, one
retrievable unit per topic. Write in clear, complete, self-contained
paragraphs per section — each section should make full sense on its own,
since only the top-matching sections are retrieved for any given question.

---

## What this application is

This is an AI-assisted IFC (Building Information Model) Compliance Checker.
It checks a 3D building model file (.ifc) against a set of building-code
rules — things like minimum room area, minimum window area relative to
room size, and window sill height — and reports which rules PASS, which
FAIL, and which cannot be evaluated because the model is missing data. The
actual PASS/FAIL decision is always made by deterministic Python
arithmetic, never by an AI model — AI is only used to explain results in
plain language and to help retrieve the right rule text for citation. This
matters for a compliance tool: the decision itself must always be
reproducible and provable, never a guess.

## Your role: Engineer

As an engineer, you can propose new compliance conditions and propose
edits to existing ones. Nothing you propose goes live immediately — every
proposal needs an admin's approval first. You can also read the full list
of currently active conditions, track the status of every proposal you've
ever submitted, and read the audit log (a history of every approved
change, read-only for you). You cannot approve or reject proposals
yourself, and you cannot manage other users' accounts — those are admin-
only actions.

## The pages available to you

- **Compliance Checker** (the main tool, linked from the top of every
  admin page): where you actually run a check on an IFC model.
- **Conditions** (`/admin/conditions`): the full list of active rules,
  with a "Propose Edit" button per rule and a "Propose New Condition"
  button at the top.
- **My Proposals** (`/admin/my-proposals`): every proposal you've ever
  submitted and its current status.
- **Audit Log** (`/admin/audit-log`): a read-only history of every change
  an admin has approved — who proposed it, who approved it, the old value,
  the new value, and when.

You do not have access to "Proposals" (the admin's approval queue) or
"Users" (user management) — those links simply won't appear for you.

## Using the Compliance Checker (the main tool)

At the top, pick a scenario: **Compliant**, **Violation**, or
**Missing Data** generates a sample model instantly for testing. **Custom**
lets you type in your own room and window dimensions and generates a model
from those. You can also **Upload IFC File** to check a real model file
instead of a generated one. Once you have a model (generated or uploaded),
click **Run Compliance Check**. Before running, you can choose the
retrieval method (Keyword or Embeddings — two different ways the system
finds the matching rule text for citation; both usually agree, this is
mostly for demonstrating/comparing the two techniques) and toggle LLM
narration on if you want an extra plain-language summary alongside the
deterministic explanation.

## Reading the results

After a check runs, you'll see one card per condition with a status:
**PASS**, **FAIL**, or **CANNOT_BE_EVALUATED**. CANNOT_BE_EVALUATED means
the IFC model was missing the data that condition needed (for example, no
window was found at all) — it is not a failure, it's "we don't have enough
information." Each card shows the calculated value, the required
value/range, and a plain explanation of why it passed or failed. Below the
individual results there's an overall badge summarizing the whole model.
There's also a "Retrieval Process" panel showing exactly how the system
matched each condition to its rule text, and a full report table (or raw
JSON) you can print or export as CSV.

## The Conditions reference panel

Near the top of the Compliance Checker page there's a collapsible
"Conditions" panel listing every currently active rule — title,
description, required value or range, and unit. This is always up to date
with whatever has been approved, including any new conditions you or other
engineers have had approved. It's meant as a quick reference so you can
see exactly what's being checked before you even run anything.

## Proposing an edit to an existing condition

From the Conditions list, click "Propose Edit" on any rule. You can change
its description, the numeric threshold (for a "minimum" type) or the
min/max values (for a "range" type), and the unit. You cannot change the
title — it's shown but greyed out, not editable, even if you try to submit
a different value it will be rejected. This is intentional: the title is
what the rest of the system uses to match a rule to its real-world meaning,
so changing it would silently break things elsewhere. Submitting shows a
confirmation dialog before anything is sent. After submitting, the change
sits as "pending" — the OLD value stays active and keeps being used for
real compliance checks until an admin approves your proposal.

## Proposing a brand-new condition

Click "Propose New Condition" from the Conditions list. You'll fill in:
a **Title** (free text, this one you do choose, since it's a new rule),
a **Description** (plain-language explanation of the rule), a **Type**
(Minimum or Range — see below), the numeric value(s), a **Unit** (like
"m", "m²", or "%"), and — importantly — a **"Checks against"** dropdown.

## Understanding condition Type: Minimum vs Range

A **Minimum** condition means a single value must be at or above a
threshold (e.g. "room area must be at least 12 m²" — here 12 is the
threshold). A **Range** condition means a value must fall between a
minimum and a maximum (e.g. "sill height must be between 0.80 m and
1.10 m"). A percentage-based rule, like "window area must be at least 10%
of room area," is still a **Minimum** type — the unit ("%") is what marks
it as a percentage, not a different type. There are only ever these two
types.

## Understanding "Checks against" (field_path)

This dropdown tells the system which real, already-extracted number from
the IFC model your new rule should compare against. It is a fixed list —
you cannot type a custom value, and the server would reject one even if
you tried, for safety reasons (this keeps the whole system fully
predictable: nothing you submit ever runs as code, it only ever picks from
a known, trusted list of numbers already pulled from the model). The
available options are:

- **Room Width (m)** — the room's width.
- **Room Length (m)** — the room's length.
- **Room Floor Area (m²)** — the room's total floor area.
- **Window Width (m)** — the window's width.
- **Window Height (m)** — the window's height.
- **Window Area (m²)** — the window's total area.
- **Window Sill Height (m)** — how high the bottom of the window is above
  the floor.
- **Window Area Ratio (%)** — the window's area as a percentage of the
  room's floor area, already calculated for you.

Pick whichever one matches what your new rule is actually about. This
field only appears when proposing a brand-new condition — when editing one
of the three original conditions, it isn't shown, because those three are
checked by their own dedicated, hand-written logic rather than this
generic lookup.

## What happens after you submit a proposal

Your proposal is saved with status **pending** and shows up on the admin's
approval queue. Nothing changes about real compliance checks yet — the
current live values (for an edit) or the absence of the new rule (for a
new condition) stay exactly as they were until an admin makes a decision.
You can check the status any time on **My Proposals**.

## Proposal statuses explained

- **Pending**: still waiting for an admin to review it. No action needed
  from you, just wait.
- **Approved**: the admin accepted it. For an edit, the live condition now
  uses your new values. For a new condition, it's now a real, active rule
  being checked on every compliance run — and it will also appear in the
  Conditions reference panel from then on.
- **Rejected**: the admin declined it, usually with a note explaining why
  (visible on My Proposals). Nothing changed on the live data. You're
  welcome to submit a corrected proposal from scratch.

## If a rejected proposal gets "reopened"

Sometimes an admin will reopen a proposal they previously rejected instead
of asking you to start over — maybe they want you to adjust just one
detail rather than resubmit everything. If this happens, you'll see a
"Reopened" badge next to that proposal on **My Proposals**, and you'll be
able to edit it in place and resubmit it for another review, rather than
creating a brand new proposal. Only proposals an admin has explicitly
reopened can be edited this way — an ordinary pending proposal cannot be
changed by you once submitted; you simply wait for the admin's decision.

## Why you see a confirmation popup before every submit

Every action that changes something — submitting a proposal, for
example — shows a small confirmation dialog first, styled to match the
rest of the app (never the browser's plain grey popup). This is
deliberate: proposing a change to a live compliance rule is meaningful, so
nothing gets submitted by accident on a single click.

## The Audit Log

This page shows a complete, permanent history of every change that has
ever actually been approved and applied to a live condition — one row per
field that changed, with the old value, the new value, who proposed it,
who approved it, and exactly when. You have read-only access to this: you
can see the full history including changes proposed by other engineers,
but you cannot add to or edit it directly — it's written automatically
whenever an admin approves a proposal. Rejected proposals never appear
here, since nothing about the live data actually changed.

## Why can't I edit the title of an existing condition?

This is permanent by design, for the three original conditions and
honestly for any condition once created, to prevent the rest of the
system from losing track of what a rule refers to.

## My proposal has been pending for a while, is something wrong?

No, this just means an admin hasn't reviewed it yet. There's no automatic
timeout; it stays pending until it's actively approved or rejected.

## I don't see a "Propose Edit" button on the Conditions page

Make sure you're logged in with an engineer account, not a viewer account.
Viewers can see conditions but cannot propose changes to them.

## What does CANNOT_BE_EVALUATED mean on a result?

It means the IFC model didn't have the data that specific condition
needed, not that the condition failed. For example, if a model has no
window defined at all, any window-related condition becomes
CANNOT_BE_EVALUATED rather than FAIL.

## I proposed a new condition but I don't see it on the Compliance Checker's Conditions panel yet

New conditions only appear there, and only get checked during a
compliance run, after an admin has approved the proposal. Check its
status on My Proposals.

## Navigating between the tool and the admin panel

There's always a link at the top of the page to get back and forth: the
admin pages have a "Compliance Checker" link, and the Compliance Checker
page has an "Admin Panel" link (which takes you to Conditions, since
that's where you spend most of your time as an engineer) plus a Logout
link.
