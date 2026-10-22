# Command line

`translate.py` translates one file from the terminal, without the web app. It is a simpler tool: it reads its provider, model and keys from flags and `.env`, not from the web app's model connections, and has no queue, comparisons or style guides.

```bash
uv run translate.py -i book.epub -sl English -tl Korean
```

This uses the provider in `LLM_PROVIDER` (default: Ollama) and the model in `DEFAULT_MODEL` (default: `qwen3:14b`), and writes `book (Korean).epub` next to the input.

## Options

| Option | Description |
|---|---|
| `-i`, `--input` | Input file: EPUB, DOCX, TXT or SRT. Required. |
| `-o`, `--output` | Output file. Default: the input name with ` (<target language>)`, or ` (refined)` with `--refine-only`. An existing file is never overwritten; ` (1)`, ` (2)`… is added instead. |
| `-sl`, `--source_lang` | Source language. Required for translation unless `DEFAULT_SOURCE_LANGUAGE` is set; there is no auto-detection on the command line. |
| `-tl`, `--target_lang` | Target language. Required, also with `--refine-only`, unless `DEFAULT_TARGET_LANGUAGE` is set. |
| `-m`, `--model` | Model name. Default: `DEFAULT_MODEL`, or the service's `<SERVICE>_MODEL` from `.env` when you choose another provider. |
| `--provider` | `ollama`, `openai`, `gemini`, `openrouter`, `mistral`, `deepseek`, `poe` or `nim`. Use `openai` for any OpenAI-compatible server. |
| `--api_endpoint` | Override the service address. Defaults: Ollama `API_ENDPOINT`, OpenAI `OPENAI_API_ENDPOINT`; other services use their own. |
| `--gemini_api_key`, `--openai_api_key`, `--openrouter_api_key`, `--mistral_api_key`, `--deepseek_api_key`, `--poe_api_key`, `--nim_api_key` | API key for that service. Defaults to the matching `*_API_KEY` in `.env`. Several comma-separated keys rotate when one hits a rate limit. |
| `--parallel N` | Passages translated at once (default 1). Only cloud services benefit; Ollama always uses 1. Passages translated together can't see each other. |
| `--text-cleanup` | Fix scan errors (OCR) and broken lines while translating. |
| `--refine` | Polish the translation in a second pass. |
| `--refine-only` | Only polish: the input is already a translation in the target language. |
| `--glossary FILE` | A glossary file (`.json` or `.csv`) of fixed translations. See [GLOSSARY.md](GLOSSARY.md#file-formats). |
| `--novel-context NAME` | Story notes to read: a file in `TranslateBook_Data/Novel_Contexts/` or a path. See [STORY_NOTES.md](STORY_NOTES.md). |
| `--auto-update-context` | Update the story notes file as the translation goes. |
| `--no-color` | Plain terminal output. |

Keys passed as flags end up in your shell history. Prefer putting them in `.env`, which is git-ignored.

## Examples

```bash
# Cloud services: the key comes from .env, or pass it as a flag
uv run translate.py -i book.epub -sl English -tl Korean --provider gemini -m gemini-2.5-flash
uv run translate.py -i book.txt -sl English -tl French --provider openrouter -m anthropic/claude-sonnet-4

# A local OpenAI-compatible server (LM Studio, llama.cpp, vLLM)
uv run translate.py -i book.txt -sl English -tl Korean --provider openai \
    --api_endpoint http://localhost:1234/v1/chat/completions -m your-model

# Keep names consistent, and build story notes while translating
uv run translate.py -i book.epub -sl English -tl Korean \
    --glossary names.csv --novel-context book_notes.txt --auto-update-context

# Polish an existing translation
uv run translate.py -i "book (Korean).epub" -tl Korean --refine-only
```

Neuralwatt and Ollama Cloud are only available in the web app.

## Behavior

- Each run is a new job. Running the same command again starts over; it doesn't resume an earlier run. Use the web app for long books you may need to stop and resume.
- The exit status is 0 on success, 1 when the translation fails, and 2 for invalid arguments.
- Without a `.env` file, the CLI prints the settings it will use and waits 5 seconds before starting. Press Ctrl+C to stop and configure.
- Webhook notifications use the same settings as the web app. See [NOTIFICATIONS.md](NOTIFICATIONS.md).

See [`.env.example`](../.env.example) for every setting the CLI reads.
