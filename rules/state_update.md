# State update rules

The rendered scene and structured commit describe the same canonical event.

## Current state

Update only facts that changed:

- datetime and place;
- continuation point;
- POV physical state;
- clothing and carried objects;
- present and nearby characters;
- unfinished movement or phrase;
- injuries, fatigue, medication, alcohol, or other relevant conditions;
- obligations, promises, risks, and deadlines.

## Characters

Stable appearance and personality do not change because of a single scene. Patch a card only for a durable change, revealed stable fact, injury, obligation, current long-term goal, or newly established connection.

Dynamic knowledge never belongs in another character's card.

## Knowledge

Every knowledge event includes:

- character ID;
- fact or version;
- status;
- source;
- replaced entry when correcting an earlier version.

Do not delete old mistakes. Mark them corrected or refuted.

## Relationships

Relationship changes are directional. Send the metric delta and factual reason. The server calculates the stored value.

Trust, attraction, respect, attachment, irritation, fear, and suspicion are independent. A positive change in one does not erase another.

Do not award points merely because the user selected a line. The delta follows an event and the NPC's established perspective.

## Plot and chronology

Chronology contains only events that occurred, their time/place, factual consequences, obligations, and deadlines. It excludes unchosen options, author guesses, and secret plans that did not occur.

Plotline patches update status, stage, stakes, next window, or causal consequences. Hidden truth changes only when the story genuinely establishes a compatible new fact.

## Technical correction

A technical correction:

- is not a story event;
- does not advance time;
- does not increment the turn number;
- does increment the state version;
- records only the corrected canonical data.
