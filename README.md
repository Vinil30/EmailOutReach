# Mailzen

Personalized email outreach and campaigns that are spam-checked before every send and delivered from the user's own Gmail.

This product does not guarantee inbox placement. It performs lightweight local spam-risk analysis before a send is attempted.

## Two workspace modes

Every account picks a mode at signup and can switch any time from **Profile**.

| | Student mode | Campaign mode |
|---|---|---|
| Who | Students doing internship, job and research outreach | Founders, marketers, sales and community teams |
| Input | A portfolio of projects (name, summary, tech, impact, link) | Brand details, an offer, a postal address and an unsubscribe line |
| Writing | Researches each company, picks the 3 most relevant projects, writes a tailored email | AI-personalized per contact, **or** a template with `{{field}}` / `{{field|fallback}}` merge fields from any CSV column |
| Extras | Project import (JSON), sign-off, goal | Compliance footer on every email, suppression list, opt-out check in the spam guard |

## Plans

| | General (free) | Premium |
|---|---|---|
| Emails | 20 in total, for life | 100 per week (resets Monday 00:00 UTC) |
| Contacts | The user's own uploaded lists | Own lists plus the admin-managed contact database |
| Writing | Templates only | Templates or AI-personalized (web research, project matching, unique drafts, AI fix-ups) |
| Duration | Always | 30 days per grant; renewals add on top of time left |

Every sent email counts toward the limit: automated sends, campaign sends and manual sends from the review queue. When the limit is hit, campaigns stop with status `quota` and unsent drafts wait as `QUOTA_REACHED`. A user whose Premium has expired falls back to the General lifetime limit.

**Buying Premium:** the "Buy Premium" buttons link to `PREMIUM_URL` (srotabase). The store emails the owner, who grants Premium from the admin panel. Grants made before the buyer signs up are applied when they create their account with that email.

## Admin panel (`/admin`)

Admins are the accounts listed in `ADMIN_EMAILS` (comma-separated). Admins can:

- grant Premium for any number of days (default 30), extend with one click, or revoke it
- see every user's plan, total sends, sends this week, database sends and automation status
- add, import (CSV/Excel/paste), deactivate or delete contacts in the shared database (`email, name, company, role, details`)

## Premium automation (`/automate`)

Premium users press **Start** and the server sends their chosen template to database contacts they haven't emailed yet, from their own Gmail, with a random 1–3 minute gap between emails. Progress is stored per user and contact, so **Stop** and **Start** continue from the next company, including after a server restart. Users see which companies they've reached, never the raw database, and unsent drafts to database contacts are never shown to them. If the spam guard holds their template, or Gmail authorization fails, automation stops with a message saying what to fix.

## Profiles and templates

Every job seeker has a profile with name, headline, school, skills, goal, a **resume link** (public Drive link) and projects. `/templates` asks one question: **Template** or **AI-personalized**.

- **Template** (all plans): one email for everyone. Only the recipient's name and company change, and the user's **featured project** stays the same. Choose from Short & direct, Project spotlight, Ask for a referral, Internship request, or write your own. Lines whose field is empty, such as a missing portfolio link, are dropped rather than left as placeholders.
- **AI-personalized** (Premium only): researches each company, picks the best-matching project and drafts a unique email; flagged drafts get one AI rewrite.

AI costs money per email, so the server enforces this: launching an AI campaign, saving the AI option, and "Fix with AI" in the review queue all return `402` for non-Premium accounts, and an AI campaign stops if Premium ends mid-run.

## Architecture

```text
Contacts (CSV / Excel / pasted)  ->  validate, dedupe, drop suppressed
        |
Background campaign runner (one contact at a time, survives page reloads)
        |
Research -> project match (students) -> write (AI or template) -> compliance footer (campaigns)
        |
Local spam-risk guard: 21 checks (+ opt-out check for campaigns)
   LOW (< 4)   -> SEND (auto mode) or ready in the review queue
   MEDIUM/HIGH -> one AI rewrite (AI mode) -> re-check -> held for review if still risky
        |
Gmail API send with bounded retries, duplicate suppression, persisted state
```

The spam guard scores capitalization, punctuation, link count, suspicious URLs, promotional phrases, urgency words, length, repetition, calls to action, subject line problems (length, "!", capitals, sales words, money signs, fake RE:), unfilled placeholders, money language, hidden or invisible text, link text that points somewhere else, generic greetings like "Dear Sir/Madam", requests for passwords or bank details, spelling tricks like "fr33", emoji overload, heavy formatting, image-heavy emails and (for campaigns) a missing unsubscribe line. Each failing check comes with a plain-language fix, and the review editor re-scores live as you type. `POST /spam/check` exposes the same guard statelessly (it powers the Spam Lab page and the landing page demo).

## Pages

- `/` landing page with a live spam-check demo
- `/dashboard` stats, setup checklist and live campaign progress
- `/campaigns/new` recipients, message (AI or template with live spam check), delivery mode
- `/campaigns` every run with progress, stop and resume
- `/waiting-mails` review queue: edit, re-score live, fix with AI, send, reject, send all ready
- `/sent-mails` delivery log with spam score and CSV export
- `/spam-check` Spam Lab for any draft
- `/profile` workspace mode, profile, resume link, projects, Gmail and suppression list
- `/templates` choose or write the email template
- `/automate` Premium automation over the shared database
- `/admin` admin panel

## API

- `POST /auth/register` (`role`: `student` or `campaigner`), `POST /auth/login`, `GET /auth/me`
- `GET|PUT /api/profile`, `POST /api/profile/projects`, `POST /api/profile/projects/import`, `PUT|DELETE /api/profile/projects/{id}`, `PUT /api/profile/suppression`
- `POST /api/campaigns/preview`, `POST /api/campaigns`, `GET /api/campaigns`, `GET /api/campaigns/stats`, `GET /api/campaigns/{id}`, `POST /api/campaigns/{id}/cancel`, `POST /api/campaigns/{id}/resume`
- `GET /human/waiting-emails`, `POST /human/save-draft`, `POST /human/rewrite`, `POST /human/send-mail`, `POST /human/reject-mail`, `GET /human/rejected-csv`
- `GET /automated/sent-emails`
- `POST /spam/check` (public)
- `GET /api/plan`, `GET /api/templates`, `POST /api/templates/preview`
- `GET /api/automation`, `POST /api/automation/start`, `POST /api/automation/stop`
- `/api/admin/*`: stats, users, premium grant/revoke, leads CRUD and import (admins only)

`/automated/run` and `/human/generate` were replaced by `POST /api/campaigns` with `mode=auto` or `mode=review`; campaigns now run in the background instead of holding the request open.

Campaign runs live in the server process. If the server restarts mid-run, the campaign is marked `interrupted` and can be resumed from the contact where it stopped.

## Gmail OAuth Setup

Create a Google Cloud OAuth client and enable the Gmail API.

Required scope:

```text
https://www.googleapis.com/auth/gmail.send
```

Local redirect URI:

```text
http://127.0.0.1:8000/gmail/callback
```

Production redirect URI:

```text
https://your-production-domain.com/gmail/callback
```

Set:

```bash
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=http://127.0.0.1:8000/gmail/callback
```

Users click **Connect Gmail**, authorize their own account, and the server stores OAuth tokens on their user record. Tokens are never kept in browser local storage.

## Failure And Retry Behavior

Before sending, every email is stored with its risk state. Gmail sends use bounded exponential backoff.

Retried:

- Gmail `429` rate limits
- network errors and timeouts
- Gmail `5xx` responses

Not retried blindly:

- invalid or rejected recipients
- expired or revoked OAuth authorization
- Gmail `4xx` permanent failures

Each record includes:

- `deliverability_risk`
- `outreach_status`
- `send_attempts`
- `email_response`
- `failure_reason`
- `send_fingerprint`

The `send_fingerprint` suppresses duplicate retry sends for the same user, recipient, subject, and body after a sent record already exists.

## Local Development

1. Create a virtual environment.
2. Install dependencies.

```bash
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env` and fill in credentials.
4. Start MongoDB.
5. Run the app.

```bash
python app.py
```

Open:

```text
http://127.0.0.1:8000
```

## Render Deployment

This repo includes `render.yaml`, so Render can create the web service from the blueprint.

Use these commands if configuring the service manually:

```bash
pip install -r requirements.txt
```

```bash
uvicorn app:app --host 0.0.0.0 --port $PORT
```

Set these environment variables in Render:

```bash
APP_ENV=production
MONGO_URI=...
MONGO_DB_NAME=OutReach
JWT_SECRET_KEY=...
JWT_ALGORITHM=HS256
CORS_ALLOW_ORIGINS=*
GROQ_API_KEY=...
GROQ_MODEL=openai/gpt-oss-120b
search_api_key=...
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=https://your-render-service.onrender.com/gmail/callback
ADMIN_EMAILS=you@example.com
PREMIUM_URL=https://srotabase.com/@vmarena/email-automation-premium
SEND_GAP_MIN_SECONDS=60
SEND_GAP_MAX_SECONDS=180
```

The health check endpoint is:

```text
/healthz
```

## Tests

```bash
pytest
```

Automated tests cover the spam-risk guard, templating and compliance footer, contact parsing, the role-aware pipeline and Gmail failure handling.

Without `GROQ_API_KEY`, template campaigns still work end to end; AI writing reports a clear error per contact. Without `search_api_key`, company research is skipped and the row's `details` column is used instead.
