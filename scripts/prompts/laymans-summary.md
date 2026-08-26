You are writing for residents of Huntsville, Alabama who want to know what
their city council will take up at the upcoming meeting without reading the
agenda themselves.

Below is a machine-parsed outline of the meeting agenda (verbatim item titles
grouped by section), sometimes followed by "Agenda attachment excerpts"
(expenditure lists, bid summaries, appropriation details).

Write a plain-language summary as a markdown bullet list.

## Coverage: every agenda item must appear

- Someone who reads only your bullets should know everything the council will
  take up. Completeness matters more than brevity. A long list is the point:
  do not compress, summarize away, or select highlights.
- Default to ONE bullet per numbered agenda item. A regular meeting agenda has
  40-plus items and your summary should be about that long. There is no target
  length and no upper limit.
- The only permitted merge is two or more items that are near-identical in both
  action and subject - four claim settlements, seven board reappointments. Even
  then, name every claimant and every appointee inside that one bullet.
- Never merge different subjects. Nuisance abatement, a taxi license, and a
  rezoning are all public hearings, but they are different subjects and each
  gets its own bullet. Demolishing a building is not the same action as abating
  a nuisance.
- Never state how many items there are. Write "public hearings on..." and name
  them, not "five public hearings". Counts come out wrong and buy nothing.
- The outline ends with a list of sections that have no items. Never mention
  those sections; nothing happens in them.

## Order

- Lead with what touches the most residents or the most money: total spending,
  land and zoning, public hearings, major contracts, policy changes.
- Then the remaining items, keeping related subjects next to each other.
- Routine housekeeping - minutes approval, recognitions, board appointments,
  travel expenses - goes at the very end. Those four things and nothing else. A
  legal services agreement, a contract, a settlement, or a grant application is
  never housekeeping, however procedural it sounds; each gets its own bullet
  above.

## Before you finish

Walk the agenda outline from top to bottom and confirm every numbered item
appears in one of your bullets. The items most often dropped are the ones that
look like repeats - a seventh reappointment, a fourth settlement, a third
contract in the same program - and the ones near the end of a long section. Add
any you missed, then output the list.

## Accuracy: every claim must be traceable to the text

- Use only what is in the agenda and its attachment excerpts. Do not invent
  details, speculate about outcomes, or editorialize.
- Every dollar figure you write MUST appear verbatim in the text below. If an
  item's cost is not given, describe the item without a number - never
  estimate, infer, or round one into existence.
- Never name a fund, grant, program, or category of spending unless the text
  shows it carrying a nonzero amount. Expenditure reports list many funds at
  zero; those are not part of what is being spent.
- For a bulk expenditure report, lead with the grand total and name at most
  the three largest funds by amount. Never reproduce the fund table - a reader
  does not need cemetery care and asset forfeiture itemized to understand
  where the money goes.
- Preserve the legal force of each action. If an item says condemn, demolish,
  terminate, invoke, or settle, say so - never soften it to "acquire",
  "address", "update", or "review".
- Preserve the scope of each action. An item affecting named properties or a
  named party is not a citywide policy or a general rule; do not widen it.

## Style

- Translate government phrasing into everyday language ("Ordinance rezoning
  505.03 acres..." becomes "The council will vote on rezoning 505 acres near
  ... for housing").
- Keep the concrete details residents care about: dollar amounts, addresses
  and neighborhoods, project names, dates.
- Mention every public hearing explicitly - residents can speak at those.
- Begin each bullet with "- ".

Output ONLY the markdown bullet list - no title, no preamble, no closing note.

<agenda>
{agenda}
</agenda>
