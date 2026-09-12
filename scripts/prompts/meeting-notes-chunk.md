You are extracting raw material from ONE PORTION of the transcript of the
{title} of {date_long}. This is part {part} of {total}.

A later pass merges every part into the finished notes. So extract only what
THIS portion contains: no introduction, no conclusion, no TL;DR, no attempt to
describe the meeting as a whole. A portion usually begins and ends mid-item;
that is expected. If an item is still being discussed when the portion ends,
record what was said and note *(continues past this portion)*.

Whisper garbles proper nouns - normalize every personal name, item number,
resolution/ordinance number, and date against the agenda text, which is
canonical for those (the agenda's first page lists the mayor, council members,
and officials - use those spellings). Attachment excerpts are canonical for
dollar amounts and recipient names.

Hard grounding rules:

- Every resolution/ordinance number you write must appear in the agenda or in
  this portion of the transcript. If an item's number is not stated, refer to
  it by subject only - never interpolate or guess a number.
- Every personal name must match the agenda's spelling when the person appears
  in the agenda; for people who appear only in the transcript (public
  commenters), use the transcript spelling and add *(name per transcript)*.
- Every dollar figure must appear verbatim in this portion, the agenda, or the
  attachment excerpts.
- Vote splits and mover/seconder attributions must come from this portion of
  the transcript; where it is unclear, write *(verify in minutes)*.
- Distinguish what already happened from what is expected to happen.
- Do not invent anything not supported by the sources.

Output a markdown document with exactly these sections, in this order. Include
every section even when it has nothing - write "(none in this portion)".

## Session facts

Only what this portion states: call-to-order time, adjournment time, presiding
officer, members present, key officials present.

## Items acted on

One table covering every item acted on in this portion:
`| Item | Subject | Outcome |`. Include resolution/ordinance numbers, appointee
names and term end dates, dollar amounts, vote splits, abstentions, and
postponement target dates.

## Discussion

Bold-led paragraphs for items with real deliberation in this portion: who said
what, concrete numbers, explicit asks made of the council, staff commitments.

## Public comments

Numbered list, one entry per speaker in this portion: name and the substance of
their ask or complaint.

## Follow-ups

Dated returns, unanswered asks, anything a future meeting should check.

Output ONLY the markdown document.

<agenda>
{agenda}
</agenda>

<attachment_excerpts>
{attachments}
</attachment_excerpts>

<transcript_portion part="{part}" of="{total}">
{chunk}
</transcript_portion>
