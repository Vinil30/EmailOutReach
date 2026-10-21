from contextlib import asynccontextmanager
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from database.fxns import ensure_indexes
from routes import admin, auth, automated, automation, campaigns, gmail, human_in_loop, profile, spam


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_indexes()
    yield


app = FastAPI(title="Mailzen", lifespan=lifespan)

cors_origins = [
    origin.strip()
    for origin in os.environ.get("CORS_ALLOW_ORIGINS", "*").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials="*" not in cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(gmail.router)
app.include_router(automated.router)
app.include_router(human_in_loop.router)
app.include_router(campaigns.router)
app.include_router(profile.router)
app.include_router(spam.router)
app.include_router(automation.router)
app.include_router(admin.router)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


PAGES = {
    "/": "index.html",
    "/login": "login.html",
    "/dashboard": "dashboard.html",
    "/campaigns": "campaigns.html",
    "/campaigns/new": "new_campaign.html",
    "/waiting-mails": "waiting_mails.html",
    "/sent-mails": "sent_mails.html",
    "/profile": "profile.html",
    "/spam-check": "spam_check.html",
    "/automate": "automate.html",
    "/templates": "templates.html",
    "/admin": "admin.html",
    "/privacy": "privacy.html",
}


def _page_route(template: str):
    def page():
        return FileResponse(f"templates/{template}")

    return page


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse("static/img/favicon.png", media_type="image/png")


@app.get("/premium-activation", response_class=HTMLResponse, include_in_schema=False)
def premium_activation():
    return """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Premium</title></head>
<body style="margin:0;min-height:100vh;display:grid;place-items:center;background:#fafaf8;color:#141414;font-family:system-ui,sans-serif;padding:24px;text-align:center;">
<p style="font-size:20px;">You will be added as Premium within 4 hours.</p>
</body></html>"""


# Google Search Console ownership files must be served from the site root.
@app.get("/google{token}.html", include_in_schema=False)
def google_site_verification(token: str):
    path = f"static/verification/google{token}.html"
    if not token.isalnum() or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(path, media_type="text/html")


for _path, _template in PAGES.items():
    app.add_api_route(_path, _page_route(_template), methods=["GET"], include_in_schema=False)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
