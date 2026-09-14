from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from database.fxns import ensure_indexes
from routes import auth, automated, gmail, human_in_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_indexes()
    yield


app = FastAPI(title="Email Outreach Automation", lifespan=lifespan)

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
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/")
def home():
    return FileResponse("templates/index.html")


@app.get("/login")
def login_page():
    return FileResponse("templates/login.html")


@app.get("/dashboard")
def dashboard_page():
    return FileResponse("templates/dashboard.html")


@app.get("/waiting-mails")
def waiting_mails_page():
    return FileResponse("templates/waiting_mails.html")


@app.get("/sent-mails")
def sent_mails_page():
    return FileResponse("templates/sent_mails.html")


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
