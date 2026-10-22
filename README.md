# TBL — Translate Books with LLMs

A web app that runs on your own computer and translates **EPUB, DOCX, TXT and SRT** files with a language model: a local one through Ollama or LM Studio, or a cloud service such as OpenAI, Gemini, OpenRouter, Ollama Cloud or Neuralwatt.

It is built for long fiction. As it translates, it keeps **story notes** on characters, genders, nicknames, terms and how people address each other, and the model reads them before every passage, so chapter 40 still matches chapter 1. Glossaries pin down names that must never change, style guides add your own instructions, and a queue runs whole series overnight.

## Quick start

You need [uv](https://docs.astral.sh/uv/getting-started/installation/) and Git. uv installs a matching Python (3.11 or newer) if you don't have one.

```bash
git clone https://github.com/3ae3ae/TranslateBooksWithLLMs-RAG-context.git
cd TranslateBooksWithLLMs-RAG-context
uv run translation_api.py
```

The first run installs the dependencies pinned in `uv.lock`. The app then opens **http://127.0.0.1:5000** in your browser. It only listens on this computer.

- Use another port: `PORT=8080 uv run translation_api.py`
- Don't open a browser: `TBL_NO_BROWSER=1 uv run translation_api.py`

Keep the terminal running. Closing the browser tab doesn't stop a translation. Stopping the server pauses it, and after the next start you continue it from the translation list.

## Your first translation

1. **Connect a model.** Open **Settings → Model connections**. A *Local Ollama* connection is always there. For a cloud service, click **Add a connection**, choose the service, paste your API key and click **Test connection**, which lists the available models. For LM Studio, llama.cpp, vLLM and similar servers, choose *OpenAI-compatible* and enter the server address.
2. **Start a translation.** Click **New translation**, drop one or more files, pick the target language and a model, and choose how story notes should work. The summary on the right estimates the number of requests, the time and the cost before you start.
3. **Follow it.** **Translations** lists running, queued and finished work. Each translation's page shows live progress, every passage side by side with its source, the story notes, and a log. Download the result from there.

The interface is in English and Korean; switch with the language button at the bottom of the sidebar.

## What it can do

| Feature | What it does |
|---|---|
| Translate, or polish | Translate a book, polish an existing translation, or translate and then polish in a second pass. |
| Formatting | EPUB and DOCX keep their formatting, or you can simplify it so far fewer passages fail. SRT timings are kept. An optional bilingual output puts the original under each paragraph. |
| [Story notes](docs/STORY_NOTES.md) | Notes the model builds and updates while translating. Start from an earlier volume's notes, view the notes as of any passage, and correct them mid-book. |
| [Glossaries](docs/GLOSSARY.md) | Fixed translations for names and terms, enforced on every passage. Import, export, or extract candidates from a book with a model. |
| Style guides | Your own instructions for translating and for polishing, such as keeping honorifics or how friends talk to each other. |
| Compare models | Run several models on the same excerpts of your book and compare quality, speed and price before committing to one. |
| Queue | Translations run one at a time in the order you choose. They survive restarts, can switch to another model halfway, and can translate the new chapters of an updated book without redoing the rest. |
| Reasoning control | Set how much each model thinks before answering (off, low, medium, high, or the service default), mapped to each service's own parameter. |
| [Notifications](docs/NOTIFICATIONS.md) | A message to your phone (ntfy, gotify), Discord, Slack or any web address when a translation finishes, fails or pauses. |

## Model services

| Service | Address | API key |
|---|---|---|
| Ollama | `http://localhost:11434` | Not needed |
| Ollama Cloud | `https://ollama.com` | Required |
| OpenAI | `https://api.openai.com/v1` | Required |
| OpenAI-compatible (LM Studio, llama.cpp, vLLM, …) | Your server | Optional |
| Gemini | `https://generativelanguage.googleapis.com/v1beta` | Required |
| OpenRouter | `https://openrouter.ai/api/v1` | Required |
| Neuralwatt | `https://api.neuralwatt.com/v1` | Required |
| Mistral | `https://api.mistral.ai/v1` | Required |
| DeepSeek | `https://api.deepseek.com` | Required |
| Poe | `https://api.poe.com/v1` | Required |
| NVIDIA NIM | `https://integrate.api.nvidia.com/v1` | Required |

A connection can hold several API keys and switches to the next one when a key hits its rate limit. See [docs/MODEL_CONNECTIONS.md](docs/MODEL_CONNECTIONS.md) for addresses, keys, reasoning, rate limits and costs.

If you used this project before and have API keys in a `.env` file, they are imported into connections once, the first time the app starts.

## Where your data lives

| Path | Contents |
|---|---|
| `TranslateBook_Data/connections.json` | Model connections, **including API keys in plain text** |
| `TranslateBook_Data/settings.json` | New-translation defaults and notification settings, including the webhook address |
| `TranslateBook_Data/Novel_Contexts/` | Story notes, one `.txt` file each |
| `TranslateBook_Data/Custom_Instructions/` | Style guides, one `.yaml` file each |
| `data/jobs.db`, `data/uploads/`, `data/logs/` | Translation jobs, their source copies and passages, and logs |
| `data/glossaries.db` | Glossaries |
| `translated_files/` | Finished translations (change with `OUTPUT_DIR` in `.env`) |

All of these are git-ignored. Back up `TranslateBook_Data/` and `data/` together. The two JSON files hold secrets: they are written readable by your user only, and should not be shared.

## Command line

`translate.py` translates a single file without the web app:

```bash
uv run translate.py -i book.epub -sl English -tl Korean -m qwen3:14b
```

The CLI reads its provider, model and keys from flags and `.env`, not from the web app's connections. See [docs/CLI.md](docs/CLI.md).

## Documentation

| Guide | Covers |
|---|---|
| [docs/MODEL_CONNECTIONS.md](docs/MODEL_CONNECTIONS.md) | Services, addresses, multiple keys, reasoning, rate limits, costs |
| [docs/STORY_NOTES.md](docs/STORY_NOTES.md) | How story notes work, the options, and fixing them mid-book |
| [docs/GLOSSARY.md](docs/GLOSSARY.md) | Glossaries: matching rules, import and export, extracting terms from a book |
| [docs/NOTIFICATIONS.md](docs/NOTIFICATIONS.md) | Webhook notifications |
| [docs/CLI.md](docs/CLI.md) | Command-line reference |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Common problems and fixes |

## License

AGPL-3.0
