from contextlib import asynccontextmanager
import hashlib
import os
import re

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
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
app.add_middleware(GZipMiddleware, minimum_size=800)


class CachedStaticFiles(StaticFiles):
    """Pages reference CSS/JS with a ?v= version, so those URLs can be cached for a year;
    unversioned files (images, demo CSVs) get a short cache instead of a check on every load."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            versioned = b"v=" in scope.get("query_string", b"")
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable" if versioned else "public, max-age=3600"
        return response


app.mount("/static", CachedStaticFiles(directory="static"), name="static")


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


ASSET_REF = re.compile(r'(/static/[^"?]+)\?v=[^"]*"')
_page_cache: dict[str, tuple[tuple, str]] = {}


def _asset_version(match: re.Match) -> str:
    path = match.group(1).lstrip("/")
    try:
        with open(path, "rb") as handle:
            digest = hashlib.md5(handle.read()).hexdigest()[:10]
    except OSError:
        return match.group(0)
    return f'{match.group(1)}?v={digest}"'


def _render_page(template: str) -> str:
    """Stamp each CSS/JS reference with its content hash, so long-lived browser caching never serves a stale file.

    Rendered pages are memoised on the template's and assets' modification times."""
    path = f"templates/{template}"
    html_mtime = os.path.getmtime(path)
    cached = _page_cache.get(template)
    if cached:
        (cached_mtime, asset_mtimes), html = cached
        if cached_mtime == html_mtime and all(os.path.getmtime(asset) == mtime for asset, mtime in asset_mtimes):
            return html
    with open(path, encoding="utf-8") as handle:
        source = handle.read()
    assets = tuple(sorted({match.group(1).lstrip("/") for match in ASSET_REF.finditer(source)}))
    html = ASSET_REF.sub(_asset_version, source)
    _page_cache[template] = ((html_mtime, tuple((asset, os.path.getmtime(asset)) for asset in assets if os.path.exists(asset))), html)
    return html


def _page_route(template: str):
    def page():
        return HTMLResponse(_render_page(template), headers={"Cache-Control": "no-cache"})

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
