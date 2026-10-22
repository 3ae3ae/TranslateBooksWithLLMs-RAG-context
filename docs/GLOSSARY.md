# Glossaries

A glossary is a list of fixed translations: this name is always translated this way. Whenever an entry's original appears in a passage, the entry goes into the request as a required translation, and it wins over the [story notes](STORY_NOTES.md).

Use a glossary for anything that must never vary: character and place names, invented words, titles, a series' established terms. Leave the rest to story notes, which follow the story and change with it.

## Making a glossary

Open **Glossaries** and click **New glossary**. Give it a name and, optionally, the languages it is for. A glossary marked for one target language shows a warning if you pick it for a translation into another.

Each entry has:

- **Original**: the text as it appears in the book. Write `A|B` to match several spellings with one translation, for example `Elizabeth|Liz|Lizzy`.
- **Translation**: what it must become.
- **Type** (optional): Character, Place, Organization, Item, Title or Other. It helps the model tell entries apart.

Type in the top row and press Enter to add an entry. Select rows to delete them or set their type together. Changes save as you go.

There are three faster ways to fill a glossary:

- **Import terms** from a CSV or JSON file (see [File formats](#file-formats)). Choose **Add to them**, which skips originals that already exist, or **Replace all**.
- **Extract terms from a book**: the model reads excerpts from a book and suggests names and terms with translations. You review the list, edit translations and types, and add the ones you want. Entries already in the glossary, or identical to their original, start unchecked.
- From **New translation**, **Extract from this book…** does the same for the file you are about to translate.

**Test on text** shows which entries match a piece of text you paste, and exactly what the model will be told.

## Using a glossary

Pick it under **New translation → Consistency → Glossary**. The translation saves a copy of the glossary when it starts, so later edits affect only translations you start afterwards. **Compare models** can use a glossary too, so you see its effect on each model.

## How matching works

- Matching is **case-sensitive**: `Hope` the name doesn't match `hope` the word.
- Chinese, Japanese and Korean originals match anywhere in the text. Other originals match whole words only, so `Ann` doesn't match inside `Anne`.
- `A|B` matches any of the spellings, and each spelling is counted.
- Longer originals are listed first, so `New York City` takes precedence over `New York`.
- At most 50 entries are sent with one passage: the most frequent in that passage, then the longest.

## Extracting terms

In **Extract terms from a book**, pick the book, how many excerpts to read (1 to 50, default 10) and how much text to send in total (500 to 6000 characters, default 6000), and a model. The excerpts are spread evenly across the book, so the same book and settings always produce the same excerpts. A short book is sent whole. The extraction is one request.

A stronger model gives better suggestions. If it suggests nothing or its answer can't be read, try a stronger model or more excerpts.

## File formats

**CSV**, with a header row:

```csv
source,target,category
Elizabeth|Liz,엘리자베스,character
Netherfield,네더필드,location
```

**JSON**, either a list of entries or a whole exported glossary:

```json
{
  "name": "Pride and Prejudice",
  "source_lang": "English",
  "target_lang": "Korean",
  "terms": [
    {"source": "Elizabeth|Liz", "target": "엘리자베스", "category": "character"},
    {"source": "Netherfield", "target": "네더필드", "category": "location"}
  ]
}
```

`category` is optional and is one of `character`, `location`, `organization`, `item`, `title`, `other`. The web import also accepts `source_term` and `translated_term` as column names, and files with a UTF-8 byte-order mark.

**Export as CSV** and **Export as JSON** write the same formats, so an exported glossary imports back unchanged.

## Storage

Glossaries live in `data/glossaries.db`. Export important ones as a backup.
