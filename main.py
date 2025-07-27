from fastapi import FastAPI, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import SQLModel, Field, Session, create_engine, select
from datetime import datetime
import shutil
import json
import os

def recover_session(session_folder: str) -> bool:
    session_dir = os.path.join(UPLOAD_DIR, session_folder)
    chunk_dir = os.path.join(session_dir, "chunks")
    combined_path = os.path.join(session_dir, "combined_interview_video.webm")
    full_video_path = os.path.join(session_dir, "interview_video.webm")

    if not os.path.isdir(chunk_dir):
        return False  # No chunks = nothing to recover

    chunk_files = sorted(os.listdir(chunk_dir))
    if not chunk_files:
        return False  # No chunks = nothing to recover

# proceed to combine chunks regardless of old .webm file


    chunk_files = sorted(os.listdir(chunk_dir))
    if not chunk_files:
        return False

    # Combine chunks
    with open(combined_path, "wb") as outfile:
        for fname in chunk_files:
            with open(os.path.join(chunk_dir, fname), "rb") as infile:
                shutil.copyfileobj(infile, outfile)

    # Clean up chunk files
    import glob
    for f in glob.glob(os.path.join(chunk_dir, "*.webm")):
        os.remove(f)
    os.rmdir(chunk_dir)

    # Database handling
    with Session(engine) as db:
        interview = db.exec(select(Interview).where(Interview.sessionId == session_folder)).first()

        # Try to recover from meta.json if DB record is missing
        if not interview:
            meta_path = os.path.join(session_dir, "meta.json")
            if os.path.isfile(meta_path):
                try:
                    with open(meta_path, "r") as f:
                        meta = json.load(f)
                    interview = Interview(
                        name=meta.get("name", "Unknown"),
                        email=meta.get("email", "Unknown"),
                        sessionId=session_folder,
                        video_path=None,
                        transcript_path=None
                    )
                    db.add(interview)
                    db.commit()
                    print(f"🆕 Created interview record from meta.json for session {session_folder}")
                except Exception as e:
                    print(f"⚠️ Failed to recover meta.json for {session_folder}: {e}")
                    return False

        # Update paths
        if interview:
            interview.video_path = f"/uploads/{session_folder}/combined_interview_video.webm"
            transcript_path = os.path.join(session_dir, "interview_transcript.txt")

            if not os.path.isfile(transcript_path):
                with open(transcript_path, "w") as tf:
                    tf.write("Transcript unavailable due to crash.")

            interview.transcript_path = f"/uploads/{session_folder}/interview_transcript.txt"
            db.add(interview)
            db.commit()
            return True

    return False



app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


DATABASE_URL = "sqlite:///interviews.db"
engine = create_engine(DATABASE_URL, echo=False)


class Interview(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    email: str
    sessionId: str
    video_path: str
    transcript_path: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

@app.post("/start-session")
async def start_session(
    sessionId: str = Form(...),
    name: str = Form(...),
    email: str = Form(...)
):
    meta_path = os.path.join(UPLOAD_DIR, sessionId, "meta.json")
    os.makedirs(os.path.dirname(meta_path), exist_ok=True)

    with open(meta_path, "w") as f:
        json.dump({"sessionId": sessionId, "name": name, "email": email}, f)

    return {"status": "session initialized"}



@app.on_event("startup")
def on_startup():
    SQLModel.metadata.create_all(engine)


@app.get("/questions")
def get_questions():
    return [
        "Tell me about yourself.",
        "What are your strengths and weaknesses?",
        "Why do you want to join our company?",
        "Describe a challenge you faced and how you handled it.",
        "Where do you see yourself in five years?"
    ]

def recover_all_sessions():
    recovered_count = 0
    for folder in os.listdir(UPLOAD_DIR):
        if recover_session(folder):
            recovered_count += 1
    print(f"[Recovery Job] ✅ Recovered {recovered_count} session(s)")



@app.post("/upload")
async def upload(
    video: UploadFile = File(...),
    transcript: UploadFile = File(...),
    sessionId: str = Form(...),
    name: str = Form(...),
    email: str = Form(...)
):
    session_dir = os.path.join(UPLOAD_DIR, sessionId)
    os.makedirs(session_dir, exist_ok=True)

    # Paths
    raw_video_path = os.path.join(session_dir, "interview_video.webm")
    combined_path = os.path.join(session_dir, "combined_interview_video.webm")
    chunk_dir = os.path.join(session_dir, "chunks")

    # Combine chunks if present
    if os.path.isdir(chunk_dir):
        chunk_files = sorted(os.listdir(chunk_dir))
        if chunk_files:
            with open(combined_path, "wb") as outfile:
                for fname in chunk_files:
                    with open(os.path.join(chunk_dir, fname), "rb") as infile:
                        shutil.copyfileobj(infile, outfile)

            # Clean up chunk files
            import glob
            for f in glob.glob(os.path.join(chunk_dir, "*.webm")):
                os.remove(f)
            os.rmdir(chunk_dir)

    # Save uploaded full video (overwritten if not used)
    with open(raw_video_path, "wb") as f:
        shutil.copyfileobj(video.file, f)

    # Save transcript
    transcript_path = os.path.join(session_dir, "interview_transcript.txt")
    with open(transcript_path, "wb") as f:
        shutil.copyfileobj(transcript.file, f)

    # Determine which video to link
    if os.path.isfile(combined_path):
        final_video_path = f"/uploads/{sessionId}/combined_interview_video.webm"
    else:
        final_video_path = f"/uploads/{sessionId}/interview_video.webm"

    # Save to DB
    interview = Interview(
        name=name,
        email=email,
        sessionId=sessionId,
        video_path=final_video_path,
        transcript_path=f"/uploads/{sessionId}/interview_transcript.txt"
    )

    with Session(engine) as session:
        session.add(interview)
        session.commit()

    return PlainTextResponse(f"Files uploaded successfully for session: {sessionId}")


@app.get("/admin/uploads")
def list_uploaded_sessions():
    with Session(engine) as session:
        interviews = session.exec(select(Interview)).all()
        data = {
            i.sessionId: {
                "name": i.name,
                "email": i.email,
                "video": i.video_path,
                "transcript": i.transcript_path,
                "timestamp": i.timestamp.isoformat()
            } for i in interviews
        }
    return JSONResponse(content=data)


@app.get("/")
def read_root():
    return {"message": "FastAPI backend with SQLite is live!"}

from fastapi import Request

from fastapi import Form  # ensure this is imported

@app.post("/upload-chunk")
async def upload_chunk(
    sessionId: str = Form(...),
    name: str = Form(...),     # ✅ added
    email: str = Form(...),    # ✅ added
    chunk: UploadFile = File(...)
):
    chunk_dir = os.path.join(UPLOAD_DIR, sessionId, "chunks")
    os.makedirs(chunk_dir, exist_ok=True)

    # Save chunk with timestamp to preserve order
    filename = f"{datetime.utcnow().isoformat().replace(':', '-')}.webm"
    chunk_path = os.path.join(chunk_dir, filename)

    with open(chunk_path, "wb") as f:
        shutil.copyfileobj(chunk.file, f)

    # ✅ Create placeholder interview if it doesn't exist
    with Session(engine) as session:
        existing = session.exec(select(Interview).where(Interview.sessionId == sessionId)).first()
        if not existing:
            interview = Interview(
                name=name,
                email=email,
                sessionId=sessionId,
                video_path=None,
                transcript_path=None
            )
            session.add(interview)
            session.commit()

    return PlainTextResponse("Chunk received.")

@app.post("/recover-incomplete-sessions")
def recover_incomplete_sessions():
    recovered_count = 0
    for folder in os.listdir(UPLOAD_DIR):
        if recover_session(folder):
            recovered_count += 1
    return PlainTextResponse(f"Recovered {recovered_count} incomplete interview sessions.")

import threading
import time

def schedule_recovery(interval=120):  # every 2 minutes 
    def run_and_reschedule():
        recover_all_sessions()
        threading.Timer(interval, run_and_reschedule).start()

    run_and_reschedule()

# Start the scheduler when app boots
schedule_recovery()

@app.get("/admin/recover-now")
def manual_recover():
    recover_all_sessions()
    return {"message": "Manual recovery complete ✅"}





