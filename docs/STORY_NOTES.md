# Story notes

A model translating passage 40 has never seen passages 1 to 39. Without help it may change a character's gender, translate a name two different ways, or switch between formal and casual speech. **Story notes** fix that: a running set of notes about the book that the model reads before every passage and updates as the story goes on.

## What the notes contain

| Section | Contents |
|---|---|
| Characters and genders | Who's who, with gender and anything that affects pronouns or speech. |
| Aliases and nicknames | Other names, nicknames and titles for the same person. |
| Name translations | Built automatically from the sections above; read-only. |
| Terms | Places, objects and invented words with their translations. |
| Forms of address | How each character currently addresses the others: honorifics, formal or casual speech. |
| Relationships | How relationships have changed so far. |

The first four are **book-wide**: they hold for the whole book. The last two **change as the story goes on**, so the app keeps a snapshot of the notes after every update. That's what lets you look at, and correct, the notes as they were at any passage.

## Choosing how to use notes

In **New translation → Consistency → Story notes**:

- **Build as I go** creates notes for this book and updates them while translating. The notes are saved in your library under the book's name.
- **Start from existing notes** begins with notes from an earlier book or volume. The translation works on its own copy and keeps updating it, so the original notes never change.

Every translation uses story notes, subtitles included. When polishing an existing translation, you can give it existing notes to read (they aren't updated) or polish without notes.

### Several files

With more than one file, choose:

- **Separate notes for each file**: each file starts fresh.
- **Volumes of one series**: files run in the order shown, and each volume starts from the previous volume's notes when it finishes. If one stops, the ones after it wait.

### Cost and speed

The notes are updated after every passage. Each update is one extra request, and passages are translated one at a time, because each passage needs the notes from the one before.

More options are under **Advanced → Story notes**:

| Option | Default | What it does |
|---|---|---|
| Notes sent per request | 1800 tokens | Only the parts most relevant to the passage are sent, up to this size. 0 sends everything. |
| Look-back text | 6000 characters | How much earlier source text the model sees when updating notes, so facts split across passages aren't lost. |
| Tidy notes every | 5 updates | Merges duplicate character entries now and then, at one extra request each time. 0 turns it off. |
| Apply the model's gender fixes right away | On | When the model decides a gender in the notes is wrong, it is fixed at once. Off: only when the text clearly says so. |

## Checking and fixing notes during a translation

Open the translation and its **Story notes** tab. There are three views:

- **Latest**: what the model is using right now. Read-only.
- **Book-wide**: characters, aliases, name translations and terms.
- **As of a passage**: the notes as they were at the passage you pick.

Fix characters, genders and terms under **Book-wide**. Fix things that change over time, such as how two characters address each other from some chapter on, under **As of a passage**.

Click **Edit**, make your changes, then **Review and save…**. The app first shows how it will store your edit: lines it rewrote into its own format, and any line it would drop. Then it re-reads the source text from that point and rebuilds every later notes update with your correction. The dialog shows how many requests that takes.

What happens to the translation depends on its state:

| Translation is | What happens |
|---|---|
| Running | It pauses, the notes are rebuilt, and it continues with the corrected notes. |
| Paused or stopped | The notes are rebuilt. Resume the translation to use them. |
| Finished, translate only | Choose **Rebuild notes only** (the translated file stays as it is) or **Rebuild and polish**, which runs a polish pass with the corrected notes and updates the file. |
| Finished, with polish | The notes are rebuilt, then the whole book is polished again with them. |

Passages that are already translated are never retranslated by a notes rebuild. A rebuild can be paused and resumed from the same tab.

## The notes library

The **Story notes** page lists every notes file. Open one to read or edit it, or create, rename, duplicate and delete notes.

Every translation works on its own copy, so editing notes in the library affects translations you start later, not ones already running. Notes that an unfinished translation is using are locked in the library; fix them from that translation's **Story notes** tab instead.

The files are plain text in `TranslateBook_Data/Novel_Contexts/`.
