# LinkedIn Profile Scraper API

Get live public LinkedIn profile data as JSON, from a plain HTTP call.

No LinkedIn API. No third party enrichment service. No API key, no signup, no account anywhere. **And no cookie needed.** You point it at a profile URL and you get structured JSON back.

```bash
curl -X POST http://127.0.0.1:8000/api/agents \
  -H 'Content-Type: application/json' \
  -d '{"input_urls":["https://www.linkedin.com/in/some-profile/"],"fetch_all_sections":true}'
```

>  ### No cookie required
>
>  **You can skip the cookie step completely.** No LinkedIn login, no `li_at`, no
>  pasting cookie blobs out of your browser devtools. Nothing to set up at all.
>
>  Public profiles are fetched logged out, so the quickstart above work on a
>  fresh install with zero configuration. Just create an agent and launch it.
>
>  A signed in session is **purely optional**, and only give you more depth on
>  profiles what hide parts of themself from logged out visitors. If you not
>  need that, ignore the whole `/api/session` group and move on.

There is a web interface included, but it is only a client. Every single thing it does is a HTTP call documented below, so you can ignore it completely and drive the API from your own code.

## Why this instead of the alternatives

The official LinkedIn API basically not give you profile data unless you are a partner. Third party vendors will sell it to you, but then you paying per record, you rate limited by them, and your queries going through somebody else server.

Here the scraper is ours, written from zero. It reads the public profile page directly and maps it to a stable set of around 60 fields. Data is fetched at the moment you ask, so it is live and not a cache from some months ago. When you self host, nothing leave your machine.

The messy parts are already handled. Lazy loaded cards what render only after scroll, empty spacer rows at top of each section, video player controls leaking into text, schools written as unlinked plain text. All of these was found against real pages and fixed.

## Base URL

| Environment | Base URL |
| --- | --- |
| Hosted demo | `https://linkedin-scrapper-nu.vercel.app` |
| Self hosted | `http://127.0.0.1:8000` |

**The demo is live for 48 hours only.** Read the section at bottom before you build on it.

## Authentication

By default there is none. Endpoints are open and you can call them straight away.

If you exposing your instance to the internet you should set your own key, and then send it. This is a key you invent yourself, it is not issued by anybody:

```bash
# on the server
PHANTOM_API_TOKEN=whatever-you-choose venv/bin/python -m phantom.main
```

Then any of these three forms work, pick what suit your client:

```bash
curl -H "Authorization: Bearer whatever-you-choose" $BASE/api/agents
curl -H "x-api-token: whatever-you-choose"          $BASE/api/agents
curl "$BASE/api/agents?token=whatever-you-choose"
```

## The basic flow

Scraping is asynchronous, because a profile take some seconds and a batch take longer. So the shape is always same four steps.

1. **Create an agent.** An agent is one saved config plus all results it ever produced
2. **Launch it.** This queue the work and return immediately
3. **Watch it**, either by stream or by polling
4. **Read the results** as JSON

### 1. Create an agent

```bash
curl -X POST $BASE/api/agents \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "Q3 prospects",
    "input_urls": [
      "https://www.linkedin.com/in/profile-one/",
      "https://www.linkedin.com/in/profile-two/"
    ],
    "fetch_all_sections": true,
    "profiles_per_launch": 50
  }'
```

Returns `201` with the agent, and you want the `id` from it.

The options what actually matter to you:

| Field | Default | What it do |
| --- | --- | --- |
| `input_urls` | `[]` | List of profile URLs. Use `input_url` if you have only one |
| `fetch_all_sections` | `false` | Turn on for the long form sections. Off means only the top card, and it is faster |
| `profiles_per_launch` | `200` | Between 1 and 1500 |
| `skip_already_processed` | `true` | Re-running not waste quota on profiles you already have |
| `enrich_company_data` | `false` | Pull extra company info |
| `save_profile_picture` | `false` | Download the picture too |
| `min_delay_seconds` | server default | Pacing between profiles. Leave it alone unless you know why |
| `max_delay_seconds` | server default | Same |
| `webhook_url` | none | We POST to it when a launch finish, so you not have to poll |
| `schedule_cron` | none | With `schedule_enabled` true, for recurring runs |

### 2. Launch it

```bash
curl -X POST $BASE/api/agents/$AGENT_ID/launch
```

Returns `202` with a launch object. Take the launch `id` if you want to follow the logs.

### 3. Watch it

Best way is Server Sent Events, then you not polling in a loop:

```bash
curl -N $BASE/api/agents/$AGENT_ID/stream
```

```js
const es = new EventSource(`${BASE}/api/agents/${agentId}/stream`)
es.onmessage = (e) => console.log(JSON.parse(e.data))
```

If you prefer polling, ask for logs and pass `after` so you only getting new lines:

```bash
curl "$BASE/api/launches/$LAUNCH_ID/logs?after=42"
```

### 4. Read the results

```bash
curl "$BASE/api/agents/$AGENT_ID/results?per_page=50"
```

```json
{
  "total": 128,
  "page": 1,
  "per_page": 10,
  "items": [
    {
      "id": 91,
      "launch_id": 12,
      "profile_url": "https://www.linkedin.com/in/some-profile/",
      "profile_slug": "some-profile",
      "scraped_at": "2026-08-31T08:19:23Z",
      "ok": true,
      "error": null,
      "duration_ms": 4180,
      "payload": {
        "first_name": "...",
        "last_name": "...",
        "linkedin_headline": "...",
        "company_name": "...",
        "linkedin_experience_json": []
      }
    }
  ]
}
```

The profile fields live inside `payload`. Check `ok` before you trust a row, and when it is `false` the reason is in `error`.

Query params, `page` from 1, `per_page` up to 200 default 10, `launch_id` to narrow to one run, `only_ok` default true so failed rows stay out of your way.

## Endpoint reference

Everything prefixed `/api`.

### Data out

| Method | Path | Returns |
| --- | --- | --- |
| `GET` | `/api/agents/{id}/results` | Paginated scraped rows |
| `GET` | `/api/agents/{id}/leads` | Paginated, shaped as leads |
| `GET` | `/api/agents/{id}/export.json` | Everything as one JSON |
| `GET` | `/api/agents/{id}/export.csv` | Everything as CSV, stable column order |

### Agents

| Method | Path | Returns |
| --- | --- | --- |
| `GET` | `/api/agents` | All agents |
| `POST` | `/api/agents` | `201` and the created agent |
| `GET` | `/api/agents/{id}` | One agent |
| `PATCH` | `/api/agents/{id}` | Updated agent. All fields optional, so you can save one piece at a time |
| `DELETE` | `/api/agents/{id}` | `204` |
| `PUT` | `/api/agents/{id}/email-provider` | Attach `hunter`, `dropcontact` or `none` |

### Launches

| Method | Path | Returns |
| --- | --- | --- |
| `POST` | `/api/agents/{id}/launch` | `202` and the launch |
| `GET` | `/api/agents/{id}/launches` | Every launch of this agent |
| `GET` | `/api/agents/{id}/stream` | SSE live progress |
| `GET` | `/api/launches/{launch_id}` | One launch and its status |
| `POST` | `/api/launches/{launch_id}/cancel` | Ask a running launch to stop |
| `GET` | `/api/launches/{launch_id}/logs` | Logs, supports `?after=<id>` |

### Session

**Optional, and most people can skip this entire section.** Public profiles scrape fine logged out and need nothing here.

A session only add depth for profiles what restrict what logged out visitors can see. If you choose to add one, cookies are encrypted at rest.

| Method | Path | Returns |
| --- | --- | --- |
| `GET` | `/api/session` | Is a cookie loaded or no |
| `POST` | `/api/session/cookies/preview` | Validate a cookie blob, nothing saved |
| `PUT` | `/api/session/cookies` | Store cookies |
| `DELETE` | `/api/session/cookies` | `204`, wiped |

### Metadata

| Method | Path | Returns |
| --- | --- | --- |
| `GET` | `/api/columns` | Every field with `key`, `label`, `kind` |
| `GET` | `/api/quota` | `used`, `cap`, `remaining` for today |
| `GET` | `/healthz` | Liveness, not under `/api` |

## What fields you get

Around 60 per profile. Instead of trusting this list, call `GET /api/columns` at startup and you never get caught out when it grow.

**Identity** `first_name`, `last_name`, `linkedin_profile_url`, `linkedin_profile_slug`, `linkedin_profile_id`, `linkedin_headline`, `linkedin_about`, `location`, `email`, `email_status`

**Company and role** `company_name`, `company_industry`, `linkedin_company_url`, `linkedin_job_title`, `linkedin_job_description`, `linkedin_job_location`, `linkedin_job_date_range`

**Education** `linkedin_school_name`, `linkedin_school_degree`, `linkedin_school_field_of_study`, `linkedin_school_date_range`

**Signals** `linkedin_followers_count`, `linkedin_connections_count`, `connection_degree`, `linkedin_is_hiring_badge`, `linkedin_is_open_to_work_badge`

**Nested blocks, real JSON arrays and not squashed strings** `linkedin_experience_json`, `linkedin_education_json`, `linkedin_certifications_json`, `linkedin_projects_json`, `linkedin_languages_json`, `linkedin_skills_json`, `linkedin_sections_json`

Field keys is a contract. New ones get added, existing ones never renamed or reordered, so you can map them safely.

## Client examples

### Python

```python
import time
import requests

BASE = "http://127.0.0.1:8000"

agent = requests.post(f"{BASE}/api/agents", json={
    "input_urls": ["https://www.linkedin.com/in/some-profile/"],
    "fetch_all_sections": True,
}).json()

requests.post(f"{BASE}/api/agents/{agent['id']}/launch")

while True:
    page = requests.get(
        f"{BASE}/api/agents/{agent['id']}/results",
        params={"per_page": 200},
    ).json()
    if page["total"]:
        break
    time.sleep(5)

for row in page["items"]:
    print(row["payload"]["first_name"], row["payload"]["linkedin_headline"])
```

### Node

```js
const BASE = 'http://127.0.0.1:8000'

const agent = await fetch(`${BASE}/api/agents`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    input_urls: ['https://www.linkedin.com/in/some-profile/'],
    fetch_all_sections: true,
  }),
}).then((r) => r.json())

await fetch(`${BASE}/api/agents/${agent.id}/launch`, { method: 'POST' })

const es = new EventSource(`${BASE}/api/agents/${agent.id}/stream`)
es.onmessage = async (e) => {
  const evt = JSON.parse(e.data)
  if (evt.status !== 'done') return
  es.close()
  const page = await fetch(
    `${BASE}/api/agents/${agent.id}/results?per_page=200`,
  ).then((r) => r.json())
  console.log(page.items.map((i) => i.payload))
}
```

## Demo is 48 hours, then you self host

Please read this one carefully so there is no surprise later.

The hosted demo stay up for **48 hours only**. After that the URL stop answering. There is no plan for keep it running and no paid tier coming after it.

It is backed by one single machine behind a tunnel, so it is a demo in the honest meaning of that word. It can go down, it can be slow, and the data inside is shared between whoever is trying it. Do not point production traffic at that URL.

**After the window, self host.** The whole codebase is in this repository and that is the real product. Self hosting is not a downgrade, it is the intended way, because then your cookies and your scraped data never leave your infrastructure.

```bash
git clone git@github.com:jha-sk/linkedin-scrapper.git
cd linkedin-scrapper/sk-jha

python3 -m venv venv
venv/bin/pip install -r requirements.txt

venv/bin/python -m phantom.main
```

It bind `127.0.0.1:8000` by default. To change:

```bash
PHANTOM_HOST=0.0.0.0 PHANTOM_PORT=8080 venv/bin/python -m phantom.main
```

Confirm it alive:

```bash
curl http://127.0.0.1:8000/healthz
```

Now swap `$BASE` in any example above to your own host and everything work same.

## Before you go to production

The daily cap and the delays exist for a reason. Scraping too aggressive is how sessions get flagged, so those settings are not decoration.

Auth is off by default, which is fine on localhost but not fine on a public address. Set `PHANTOM_API_TOKEN` the moment you bind to anything other than loopback.

You responsible for how you use this. Respect LinkedIn terms, respect the rate limits, and respect the people whose data you collecting. Only public profile data is touched here, but public is not meaning consequence free.

## License

See [LICENSE](LICENSE).
