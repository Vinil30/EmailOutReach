# Failure-Aware Email Outreach

Generate personalized student outreach, analyze spam/deliverability risk before sending, correct or block risky messages, and send accepted mail through the user's own Gmail account.

This product does not guarantee inbox placement. It performs lightweight local spam-risk analysis before a send is attempted.

## Architecture

```text
Generate personalized email
        |
Local spam-risk guard
        |
Risk score + signals + reasons
        |
Risk decision
   LOW -> SEND
   MEDIUM -> LLM rewrite -> local guard again -> SEND or REVIEW
        |
Gmail API send
        |
Retry transient failures, persist final state
```

The LLM writes and rewrites email content. The local deterministic guard determines pre-send risk from capitalization, punctuation, links, suspicious URLs, promotional phrases, urgent language, length, repeated phrases, and call-to-action density. Gmail API responses and persisted application state determine whether an email was actually sent.

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
search_api_key=...
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=https://your-render-service.onrender.com/gmail/callback
```

The health check endpoint is:

```text
/healthz
```

## Tests

```bash
pytest
```

Automated tests cover the local spam-risk guard and Gmail failure handling.
