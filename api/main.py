import os
import re
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

app = FastAPI(title="Content Repurposing Engine API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://content-repurposing-engine-eight.vercel.app"],
    allow_methods=["*"],
    allow_headers=["*"],
)

YOUTUBE_URL_PATTERN = re.compile(
    r"^(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/)[\w-]+"
)


class JobCreateRequest(BaseModel):
    youtube_url: str

    @field_validator("youtube_url")
    @classmethod
    def validate_youtube_url(cls, value: str) -> str:
        if not YOUTUBE_URL_PATTERN.match(value.strip()):
            raise ValueError("Must be a valid YouTube video URL")
        return value.strip()


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/jobs")
def create_job(payload: JobCreateRequest):
    result = supabase.table("jobs").insert(
        {
            "youtube_url": payload.youtube_url,
            "status": "PENDING",
        }
    ).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create job")

    job = result.data[0]
    return {"job_id": job["id"], "status": job["status"]}


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    result = supabase.table("jobs").select("*").eq("id", job_id).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Job not found")

    return result.data[0]