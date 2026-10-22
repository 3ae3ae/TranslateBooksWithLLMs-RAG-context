# Notifications

The app can call a web address when a translation finishes, fails or pauses on its own, so a long book can run while you're away. Anything that accepts an HTTP request works: ntfy or gotify for phone pushes, Discord and Slack webhooks, Healthchecks.io, or your own endpoint.

## Setting it up

Open **Settings → Notifications**.

1. Turn on **Send notifications**.
2. Under **Start from**, pick a preset (ntfy, gotify, Discord, Slack, Healthchecks.io) to fill in a template, then replace the placeholder address with yours.
3. Choose the events under **Notify when**.
4. Click **Save**, then **Send a test**. The test uses the saved settings and sends a *success* event.

| Field | Notes |
|---|---|
| Web address | Where the request goes. Treated like a password: after saving, the app shows only its last characters. Leave it blank to keep the saved one. |
| Method | `POST` (default), `PUT` or `GET`. `GET` sends no body. |
| Headers (JSON) | A JSON object, for example `{"Authorization": "Bearer YOUR_TOKEN_HERE"}`. Stored like the address. |
| Message body (JSON) | Leave empty for the default body. Otherwise a JSON template; see [Placeholders](#placeholders). |

## Events

| Event | Sent when |
|---|---|
| `success` | A translation finishes. |
| `failure` | A translation fails. |
| `system_paused` | A translation stops without you asking: the service rate-limits it, or the app restarts in the middle of it. |
| `queue_finished` | The last translation in the queue is done. |

Pausing a translation yourself doesn't send anything.

## Placeholders

The address, header values and every string in the body can contain placeholders in braces:

| Placeholder | Value |
|---|---|
| `{event}` | `success`, `failure`, `system_paused` or `queue_finished` |
| `{file}` | Input file name |
| `{output}` | Output file path |
| `{duration_seconds}` | Run time in seconds |
| `{provider}`, `{model}` | The service and model |
| `{source_lang}`, `{target_lang}` | The languages |
| `{error}` | The error message, on failure |
| `{translation_id}` | The translation's internal id |

Not every event has every value: `system_paused` and `queue_finished` carry little more than `{event}` and `{translation_id}`. A missing value becomes empty text.

Placeholders use Python's format syntax, so `{duration_seconds:.0f}` rounds to whole seconds. Put them inside JSON strings, because the body must be valid JSON before the values are filled in: `"took {duration_seconds:.0f}s"` works, a bare `{duration_seconds}` outside quotes doesn't. If a string has a placeholder that can't be filled, it is sent unchanged.

Without a body template, the app sends:

```json
{
  "title": "...",
  "message": "...",
  "event": "success",
  "file": "book.epub",
  "duration_seconds": 1234.5,
  "error": null
}
```

## Recipes

**ntfy** (free phone pushes; install the ntfy app and subscribe to a topic only you know):
address `https://ntfy.sh/your-unique-topic`, no body. ntfy shows the default JSON as the message text.

**gotify**: address `https://gotify.example.com/message?token=YOUR_TOKEN_HERE`.

**Discord**: a channel webhook address, with the body

```json
{"content": "Translation **{event}**: `{file}` in {duration_seconds:.0f}s"}
```

**Slack**: an incoming-webhook address, with the body

```json
{"text": "Translation {event}: {file} ({duration_seconds:.0f}s)"}
```

**Healthchecks.io**: method `GET`, address `https://hc-ping.com/your-uuid-here`, and only **A translation finishes** (or **The whole queue is done**) selected. Each finished translation pings the check, and Healthchecks alerts you when the pings stop arriving on schedule.

## Privacy and failures

The address and headers are stored in plain text in `TranslateBook_Data/settings.json`, readable by your user only. Don't share that file. If a token leaks, revoke it at the service.

A notification that fails never affects the translation. The app logs only that the notification failed, without the address or response.

## Settings from `.env`

The `NOTIFY_*` variables in `.env` (`NOTIFY_WEBHOOK_URL`, `NOTIFY_WEBHOOK_METHOD`, `NOTIFY_WEBHOOK_HEADERS`, `NOTIFY_WEBHOOK_PAYLOAD`, `NOTIFY_ON_SUCCESS`, `NOTIFY_ON_FAILURE`, `NOTIFY_ON_INTERRUPTION`, `NOTIFY_TIMEOUT_SECONDS`) are copied into the settings once, when `settings.json` is first created. After that, the Settings page is the only source. The command-line tool also sends notifications using the same settings.
