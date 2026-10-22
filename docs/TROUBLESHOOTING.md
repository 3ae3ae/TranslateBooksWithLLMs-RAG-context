# Troubleshooting

When something goes wrong, the translation's **Log** tab usually says why. The same log is kept in `data/logs/<translation id>.jsonl`. For more detail in the terminal, add `DEBUG_MODE=true` to `.env` and restart.

## The app

**Port 5000 is already in use.** Start on another port: `PORT=8080 uv run translation_api.py`, or put `PORT=8080` in `.env`.

**The app exits right after starting with a folder error.** It checks that it can write to the output folder (`translated_files/`, or `OUTPUT_DIR` in `.env`) and stops if it can't. Pick a folder you can write to; on Windows, Controlled Folder Access or antivirus software can block it.

**The page shows "Unauthorized" or stops updating.** The app makes a new access token each time it starts, and an open page reloads itself when it notices. If it doesn't, refresh the page.

**Translations stopped when I closed the terminal.** The terminal is the app; keep it running. Closing only the browser tab is fine. After a restart, a translation that was running is paused and the queue is held until you act: **Resume** on that translation continues it first, or **Resume queue** starts the next one.

**A warning about Ollama at startup.** The app checks for a local Ollama when it starts. If you only use cloud services, ignore it.

## Connecting to a model

**Can't reach Local Ollama.** Make sure Ollama is running (`ollama serve`, or the Ollama app) and answers at `http://localhost:11434/api/tags`. Then click **Try again** next to the model, or **Test connection** in Settings.

**My model isn't in the list.** For Ollama, download it first: `ollama pull qwen3:14b`, and check the exact name with `ollama list`. For other services, check the name on the service's site. You can type a model name that isn't listed.

**Test connection works but translations fail.** The test lists models with the first key and, if you chose a model, sends it one tiny message. A translation can still fail because of the specific model or another key. Check the log for the HTTP status:

| Status | Usually means | What to do |
|---|---|---|
| 401, 403 | Invalid or revoked key | Replace the key in the connection. |
| 402 | No credit left | Top up, or switch models with **Change model and resume…**. |
| 404 | The model name doesn't exist (any more) | Pick another model. |
| 429 | Rate limit | See below. |

**OpenAI-compatible server isn't found.** Enter the base address, for example `http://localhost:1234/v1` for LM Studio or `http://localhost:8080` for llama.cpp. You don't need `/chat/completions`. Some local servers also need a key.

## During a translation

**It keeps hitting rate limits.** Add more API keys from different accounts to the connection (one per line), lower **Requests at once**, or set **When the service limits requests** to *Wait and continue automatically*. On a daily quota, automatic waiting can last until the quota resets; pause it or use **Change model and resume…** instead. See [MODEL_CONNECTIONS.md](MODEL_CONNECTIONS.md#rate-limits).

**It's slow.** Local models translate one passage at a time. Story notes that update while translating also force one request at a time, and each update is an extra request; raise **Update every** to update less often. For cloud services without story-note updates, raise **Requests at once** in the connection.

**Passages were left untranslated, or formatting is slightly off.** The translation finishes as *Done · some passages failed* and lists the passages. **Retry failed passages** redoes only those. If the same passages keep failing, they often have complex inline formatting: start again with **Simplify formatting**, a smaller **Passage size**, or a different model.

**The local model runs out of context or repeats itself.** Each request holds the passage, the instructions, the relevant story notes and glossary entries, and room for the answer. Lower **Passage size** or **Notes sent per request** under **Advanced**, or use a model with a larger context. For Ollama, `OLLAMA_NUM_CTX` in `.env` sets the context size, and the app enlarges it when a request needs more.

**Reasoning "Off" seems ignored.** Some models always reason, and some services ignore the setting. The app sends the closest thing each service has; see [MODEL_CONNECTIONS.md](MODEL_CONNECTIONS.md#reasoning).

**I changed a connection, glossary or style guide, but the translation didn't change.** A translation keeps the settings it started with. Only API keys are read fresh when it resumes. To use different settings, start a new translation, or use **Change model and resume…** for the model.

**A translation shows "Paused (connection removed)".** Its connection was deleted. Pick another model with **Change model and resume…**.

**The story notes are wrong.** Fix them on the translation's **Story notes** tab; see [STORY_NOTES.md](STORY_NOTES.md#checking-and-fixing-notes-during-a-translation). Notes in the library that a running translation uses are locked for the same reason.

**Translate new chapters redid more than expected.** Passages are reused only while the new source matches the old one from the start. An edit early in the book means everything after it is translated again.

## Files

**My file is rejected.** The app accepts EPUB, DOCX, TXT and SRT up to 100 MB each. Empty files, renamed executables, EPUB or DOCX files that aren't valid ZIP archives (or have more than 10,000 entries), and subtitles with more than 10,000 cues are refused.

**Scanned PDFs or images.** The app doesn't read PDFs or images. Extract the text first; **Fix scan errors (OCR)** then fixes recognition errors and broken lines while translating.

**Where is my translation?** In `translated_files/`, or the folder set with `OUTPUT_DIR`. **Open output folder** on the translation list opens it. An interrupted EPUB is saved with a `[partial]` prefix.

## Notifications

**The test notification doesn't arrive.** Save first: the test uses the saved settings. Make sure **Send notifications** is on and the address is right. The app logs only that a notification failed, not why; try the address with `curl` to see the service's answer. Placeholders must sit inside JSON strings; see [NOTIFICATIONS.md](NOTIFICATIONS.md#placeholders).
