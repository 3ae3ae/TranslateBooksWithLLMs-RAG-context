# Model connections

A **connection** is one model service plus how to reach it: its type, address, API keys and request settings. You manage them in **Settings → Model connections**. Every translation, comparison and term extraction picks a model from one of your connections.

The default connection and model (marked *Default*) are preselected for new translations. The sidebar shows the default model with a green dot, or a red dot when the service can't be reached.

## Services

| Type | Default address | API key | Reasoning control |
|---|---|---|---|
| Ollama | `http://localhost:11434` | Not needed | Off / low / medium / high |
| Ollama Cloud | `https://ollama.com` | Required ([ollama.com/settings/keys](https://ollama.com/settings/keys)) | Off / low / medium / high |
| OpenAI | `https://api.openai.com/v1` | Required ([platform.openai.com](https://platform.openai.com/api-keys)) | Off / low / medium / high |
| OpenAI-compatible | None, you enter it | Optional | Best effort |
| Gemini | `https://generativelanguage.googleapis.com/v1beta` | Required ([Google AI Studio](https://aistudio.google.com/apikey)) | Off / low / medium / high |
| OpenRouter | `https://openrouter.ai/api/v1` | Required ([openrouter.ai/keys](https://openrouter.ai/keys)) | Off / low / medium / high |
| Neuralwatt | `https://api.neuralwatt.com/v1` | Required (your Neuralwatt account) | Best effort |
| Mistral | `https://api.mistral.ai/v1` | Required ([console.mistral.ai](https://console.mistral.ai/api-keys)) | Best effort |
| DeepSeek | `https://api.deepseek.com` | Required ([platform.deepseek.com](https://platform.deepseek.com/api_keys)) | On / off |
| Poe | `https://api.poe.com/v1` | Required ([poe.com/api_key](https://poe.com/api_key)) | Best effort |
| NVIDIA NIM | `https://integrate.api.nvidia.com/v1` | Required ([build.nvidia.com](https://build.nvidia.com/)) | Best effort |

*Best effort* means the app sends the setting, but the service or model may ignore it.

A built-in **Local Ollama** connection always exists. You can edit its address and model, but not delete it or change its type.

**OpenAI-compatible** covers any server that speaks the OpenAI chat API: LM Studio, llama.cpp, vLLM, LocalAI, a self-hosted gateway, and so on.

**Ollama Cloud** runs Ollama's hosted models with an API key and is billed through your Ollama plan, so the app shows its cost as *Uses your Ollama plan* instead of a price. Ollama models whose names end in `-cloud` or `:cloud` also run in Ollama's cloud even through a local Ollama, so the app treats them as remote.

## Adding a connection

Click **Add a connection**, choose the service, and fill in:

| Field | Notes |
|---|---|
| Name | Shown in model pickers. |
| Server address | Paste the base address. A full URL ending in `/chat/completions`, `/models`, or Ollama's `/api/...` also works; the app strips the endpoint part. For an OpenAI-compatible server with no path, `/v1` is added. User names, passwords, and key-like query parameters are not allowed in the address. |
| API key | One per line. See [Several API keys](#several-api-keys). |
| Runs on this computer | Set automatically for `localhost`, `127.0.0.1`, `::1` and `*.local` addresses. Turn it on for a model on another machine in your network if you want it treated as local. |
| Default model | Preselected for new translations. |
| Requests at once | Passages sent in parallel. Default 4, or 1 for local models. Passages translated at the same time can't see each other, and story notes that update during translation force one at a time anyway. |
| Response timeout | How long to wait for one answer before retrying. Default 300 s, or 900 s for local models. |
| Attempts per request | Including the first try. Default 2. |
| When the service limits requests | *Wait and continue automatically* or *Pause until I resume*. See [Rate limits](#rate-limits). |
| Temperature | Leave at *Provider default* unless you have a reason. |

**Test connection** lists the models the service offers and, when a model is chosen, sends it a one-token test message. It uses the first key only. You can also type a model name that isn't listed.

## Several API keys

A connection can hold several keys, one per line. Each request takes the next key in turn. When a key hits its rate limit (HTTP 429), it rests for as long as the service asks, and the next free key is used right away. This only helps when the keys have separate quotas, for example keys from different accounts.

Keys that are invalid, out of credit or revoked (HTTP 401, 402, 403) are not skipped automatically: the request fails right away and the translation stops. Remove or replace the key in the connection.

Rate-limit cooldowns live in memory and reset when the app restarts.

## Rate limits

When every key of a connection is rate-limited, the app waits for the earliest one to free up, using the service's `Retry-After` or `X-RateLimit-Reset` header, or backing off 4, 8, 16, 32 and then 60 seconds. If the service keeps refusing, the connection's **When the service limits requests** setting decides:

- **Wait and continue automatically**: the translation shows *Rate limited · retrying soon*, waits as long as the service asks (or the number of seconds you set), and continues from where it stopped. It keeps trying. On a daily quota that can mean waiting until the quota resets; pause it or switch models if you don't want that.
- **Pause until I resume**: the translation pauses, and you resume it from the translation list.

Other failures such as timeouts and server errors are retried up to *Attempts per request*. A model that doesn't exist (HTTP 404) fails right away.

## Reasoning

Every translation, comparison column and model change has a **Reasoning** setting: *Off*, *Low*, *Medium*, *High* or *Provider default*. Translation rarely needs reasoning; higher levels are slower and cost more. The app translates the setting into each service's own parameter:

| Service | Off | Low / Medium / High |
|---|---|---|
| Ollama, Ollama Cloud | `think: false` (`"low"` for gpt-oss, which can't turn it off) | `think: "low"` / `"medium"` / `"high"` |
| OpenAI | The lowest effort the model allows (`none`, `minimal` or `low`), or nothing for models without a setting | `reasoning_effort` |
| Neuralwatt | `reasoning_effort: "none"` | `reasoning_effort` |
| OpenRouter | `reasoning: {enabled: false}` | `reasoning: {effort: …}` |
| Gemini 2.5 | Thinking budget 0 (128 for Pro) | Budget 1024 / 8192 / 24576 |
| Gemini 3 and later | `thinkingLevel` minimal or low | `thinkingLevel` |
| DeepSeek | `thinking: disabled` | `thinking: enabled` |
| OpenAI-compatible, NVIDIA NIM | `chat_template_kwargs: {enable_thinking: false}` | `reasoning_effort` |
| Mistral, Poe | `none` where the model accepts it | `high` for Mistral, `reasoning_effort` for Poe |

*Provider default* usually sends nothing. Models that always reason may ignore *Off*. If a service rejects one of these parameters (HTTP 400 or 422), the app retries the request without it.

## Costs and estimates

The model picker shows a price per million input and output tokens when it is known: from the model list for OpenRouter, Poe and Neuralwatt, and from a bundled price table for other services. Local models show *on this computer* and cost nothing.

Before you start a translation, the summary counts the requests from the book's actual passages, plus story-notes updates and the polish pass if you chose one, and estimates the cost from the price. The time estimate comes from your earlier translations with the same connection and model, so a fresh install shows *Time unknown* until you have one (a run on **Compare models** doesn't count).

## How jobs use connections

A translation stores its settings when it is created: model, reasoning, request settings, glossary, style guide and story-notes options. Editing a connection later doesn't change queued or running translations. Only the API keys are read fresh each time a translation starts or resumes, so a replaced key takes effect on the next resume.

If you delete a connection that a translation uses, that translation pauses until you pick another model with **Change model and resume…**. Deleting the default connection makes Local Ollama the default.

## Importing keys from `.env`

The first time the app starts without `TranslateBook_Data/connections.json`, it creates connections from your `.env` file and environment:

- Local Ollama from `OLLAMA_API_ENDPOINT` and `DEFAULT_MODEL`
- One connection per service that has a key: `OPENAI_API_KEY`, `NEURALWATT_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `MISTRAL_API_KEY`, `DEEPSEEK_API_KEY`, `POE_API_KEY`, `NIM_API_KEY`, and `OLLAMA_API_KEY` for Ollama Cloud. A comma-separated value becomes several keys. `<SERVICE>_API_ENDPOINT` and `<SERVICE>_MODEL` set the address and default model.
- An `OPENAI_API_ENDPOINT` that isn't api.openai.com becomes an OpenAI-compatible connection.
- The service named in `LLM_PROVIDER` becomes the default.

This happens once. After that, `connections.json` is the only source, and changes to `.env` don't affect the web app. To import again, stop the app, move `connections.json` away, and start it.

`connections.json` stores keys in plain text, readable by your user only. Don't share it or commit it.
