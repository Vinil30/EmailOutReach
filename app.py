from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
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


for _path, _template in PAGES.items():
    app.add_api_route(_path, _page_route(_template), methods=["GET"], include_in_schema=False)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
