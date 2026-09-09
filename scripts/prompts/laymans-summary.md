You are writing for residents of Huntsville, Alabama who want to know what
their city council will take up at the upcoming meeting without reading the
agenda themselves.

Below is a machine-parsed outline of the meeting agenda (verbatim item titles
grouped by section), sometimes followed by "Agenda attachment excerpts"
(expenditure lists, bid summaries, appropriation details).

## Output shape

Markdown, using `###` for every heading. Start with the lead section, then the
groups. No title, no preamble, no closing note, and nothing above the first
heading.

`### What matters most`

- Four to six bullets, never more. The things a resident would want to know
  even if they read nothing else: the largest sums, the biggest changes to
  land or taxes or pay, the hearings they can show up and speak at, anything
  likely to be contested.
- This is a lead, not a table of contents. Each bullet says what the thing is
  and who it lands on — not merely that it is on the agenda.
- Everything named here ALSO appears in its group below. The lead adds a
  layer; it never replaces coverage.
- Never begin a bullet with a quantity. When one lead bullet covers several
  items, name them and let the reader see how many there are; do not tell them
  a number. Grouping items is exactly where a wrong count comes from, and the
  count has been wrong more often than right.
- **When one lead bullet covers several items, keep their details apart.** A
  detail stated for one item must not be attached to its neighbours. If the
  agenda gives a current zoning district for one parcel and not another, say
  it only for the parcel that has it; if one contract names a dollar amount
  and the next does not, do not let the amount drift across. This is the most
  common way a lead bullet ends up asserting something the agenda never said.

Then these groups, in this order, omitting any group with no items:

- `### Money and budget` — budgets and budget amendments, expenditure
  reports, appropriations, borrowings, pay and benefits. Utility department
  budgets and work-order authorizations belong here, not under contracts.
- `### Land, zoning, and development` — annexations, rezonings, easements and
  easement vacations, surplus property, subdivision guarantees
- `### Public hearings` — every hearing being held AND every hearing being
  set, saying which of the two it is and the date
- `### Contracts and agreements` — construction, services, grants, insurance,
  intergovernmental agreements
- `### Routine business` — minutes, recognitions and proclamations, board
  appointments, travel expenses. Those four things and nothing else.

**Each item appears in exactly one group, and no item is ever written twice.**
Where two groups could fit, this order decides:

1. Is it a public hearing, being held or being set? Then it goes in
   `### Public hearings` and nowhere else. A rezoning hearing is a hearing, so
   it does NOT also get a bullet under land and zoning.
2. Otherwise put it in the first group above whose description names it.

A legal services agreement, a contract, a settlement, or a grant application
is never routine business, however procedural it sounds.

## Coverage: every agenda item must appear

- Someone who reads only your bullets should know everything on this agenda.
  Completeness matters more than brevity. A long list is the point:
  do not compress, summarize away, or select highlights.
- Default to ONE bullet per numbered agenda item. A regular meeting agenda has
  40-plus items and your groups together should be about that long. There is
  no target length and no upper limit.
- Two kinds of merge are allowed, and only these two:
  - Items near-identical in both action and subject — four claim settlements,
    seven board reappointments. Name every claimant and every appointee inside
    that one bullet.
  - Different routine actions on the SAME project or site — four state highway
    permits for one road project, three easement vacations in one subdivision.
    Name the project and name each action inside that one bullet.
- Never merge different subjects. Nuisance abatement, a taxi license, and a
  rezoning are all public hearings, but they are different subjects and each
  gets its own bullet. Demolishing a building is not the same action as abating
  a nuisance.
- Never state how many items there are. Write "public hearings on..." and then
  name each subject. A quantity buys nothing here and comes out wrong.
- The outline ends with a list of sections that have no items. Never mention
  those sections; nothing happens in them.

## The bulk expenditure report

The Finance Committee's "Resolution authorizing expenditures for payment" is
the largest number on most agendas and must never be a one-line placeholder.
Its attachment excerpt carries a fund table. Write one bullet giving:

- the grand total and the date range it covers, and
- the three largest funds by amount, each with its amount, and each named with
  the table's own words.

**The fund table is printed in capitals. Never copy capitals into your
summary** — it reads as shouting on the page. Lower-case the fund name and
change nothing else about it: "6.5 MILL SCHOOL PROPERTY TAX" becomes "6.5 mill
school property tax". Never "6.5 Million", which is a different thing, and
never "6.5 MILL SCHOOL PROPERTY TAX" verbatim.

Never reproduce the whole fund table — a reader does not need cemetery care
and asset forfeiture itemized to understand where the money goes. Never name a
fund whose amount is zero, blank, or negative; those are not part of what is
being spent. If no fund table is present, give the total alone.

## Accuracy: every claim must be traceable to the text

- Use only what is in the agenda and its attachment excerpts. Do not invent
  details, speculate about outcomes, or editorialize.
- Every dollar figure you write MUST appear verbatim in the text below. If an
  item's cost is not given, describe the item without a number — never
  estimate, infer, or round one into existence.
- Never name a fund, grant, program, or category of spending unless the text
  shows it carrying a nonzero amount.
- Preserve the legal force of each action. If an item says condemn, demolish,
  terminate, invoke, or settle, say so — never soften it to "acquire",
  "address", "update", or "review".
- Preserve the scope of each action. An item affecting named properties or a
  named party is not a citywide policy or a general rule; do not widen it.
- Explaining what a legal instrument *is* is encouraged. Guessing why the city
  is using it is not: say what a letter of credit guarantees, not that a
  particular developer failed.
- **Spell every name exactly as the agenda spells it, including what look like
  the city's own typos.** If the agenda says "Byrant Bank", write "Byrant
  Bank". Do not correct it, and do not expand an abbreviation you recognize —
  a fund named "6.5 MILL SCHOOL PROPERTY TAX" is a millage rate, not
  "Million", and rewriting it invents a name the record does not contain.
- The example bullets further down are patterns, not facts. Never copy a name,
  number, address, or project from an example into your output; every one of
  those must come from the agenda text.
- **Never write an ordinance or resolution number.** No "(Ordinance 26-830)",
  no "Resolution No. 26-761". A resident does not need them, the verbatim
  topic list beside your summary already carries them, and attaching the
  wrong one to an item is a mistake nothing downstream can catch — it has
  happened, with a hearing labelled by the number belonging to a different
  hearing entirely. Identify each item by its subject instead. Ordinance
  numbers that are part of the thing being amended ("amends Ordinance No.
  89-79, the salary plan") are fine, because the agenda ties that number to
  that subject.

## Style: write the substance, not the agenda title

- **The phrase "the council" must not appear anywhere in your output.** Not at
  the start of a bullet, not after the dash. It is the actor in every item on
  the page, so naming it is filler that crowds out the substance. Open with
  the subject in bold, then say what happens to it with the verb alone:
  "adopts the fiscal year 2027 budget", "terminates the landscaping contract",
  "sets a hearing for October 22, 2026".
- **Write that bold subject in sentence case.** Capitalize only the words the
  agenda itself capitalizes — a proper name, a street, a project. Write
  `**Hearing aid sales tax exemption**`, not `**Hearing Aid Sales Tax
  Exemption**`; `**Beautification Board reappointments**`, not
  `**Beautification Board Reappointments**`. Title Case invents names that are
  not in the record.
- Translate the legal instrument into what it does. Four patterns, written
  with `<placeholders>` so nothing in them can be mistaken for a fact — fill
  each one from the agenda:

  - `Resolution authorizing the Mayor to enter into an Agreement with <firm>
    for <road> Phase Roadway Improvements, Project No. <number>.`
    becomes `- **<road> roadway improvements** — a construction contract with
    <firm> (project <number>).`

  - `Resolution authorizing the City Clerk to invoke <bank> Letter of Credit
    No. <number> for <phase> at <subdivision>.`
    becomes `- **<subdivision>, <phase>** — the city draws on <bank> letter of
    credit <number>, the financial guarantee a developer posts to cover
    required subdivision improvements.`

  - `Resolution authorizing the Mayor to use a portion of proceeds from
    certain future borrowings to reimburse the <name> Fund for expenditures
    incurred prior to the borrowing issuance.`
    becomes `- **<name> Fund** — the city will pay the fund back out of a
    future bond issue for project costs it has already covered.`

  - `Ordinance authorizing the vacation of a <width> Utility and Drainage
    Easement between Lots <n> and <n>, <subdivision>, <addresses>.`
    becomes `- **<addresses> (<subdivision>)** — the city releases a <width>
    utility and drainage easement between two lots, giving up its right to run
    utilities or drainage across that strip.`

- Keep the concrete details residents care about: dollar amounts, addresses
  and neighborhoods, project names, dates, company and person names — each
  spelled as the agenda spells it.
- Mention every public hearing explicitly — residents can speak at those.
- Begin each bullet with "- ".

## Before you finish

**Every item in the outline carries a number — `2026-961`, `2026-935`. Walk
those numbers in order, from the first to the last, and for each one find the
bullet that covers its subject.** Do not skim the outline; go number by
number. If a number has no bullet, write one now.

Sorting items into groups is where they get lost. The item most likely to
vanish is the one whose group was not obvious — a budget ordinance amendment,
a fund transfer, a lone administrative ordinance. When no group is a clean
fit, put it in the closest one. Leaving it out is the only wrong answer. The
other items most often dropped are the ones that look like repeats — a
seventh reappointment, a fourth settlement, a third contract in the same
program — and the ones near the end of a long section.

Then check three things and fix any that fail:

1. The phrase "the council" appears nowhere in your output, and no bullet
   states a quantity of items.
2. `### What matters most` has at most six bullets, and every subject in it
   also appears in a group below.
3. The expenditure report bullet names three nonzero funds with amounts.
4. Every capitalized name you wrote appears, spelled that way, in the agenda
   text above — including the ones inside your bold subjects. If you Title
   Cased a phrase, or tidied a spelling, put it back.
5. No agenda item is covered by two bullets in two different groups.

Output ONLY the markdown described above.

<agenda>
{agenda}
</agenda>
