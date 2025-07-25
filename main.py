import asyncio
from fastapi_utils.tasks import repeat_every

from fastapi import FastAPI, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import SQLModel, Field, Session, create_engine, select
from datetime import datetime
import shutil
import os


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


from typing import Optional

@app.post("/start-session")
def start_session(sessionId: str = Form(...), name: str = Form(...), email: str = Form(...)):
    with Session(engine) as session:
        # Check if already exists (to avoid duplicates)
        existing = session.exec(select(Interview).where(Interview.sessionId == sessionId)).first()
        if existing:
            return PlainTextResponse("Session already initialized", status_code=200)

        interview = Interview(
            name=name,
            email=email,
            sessionId=sessionId,
            video_path="",
            transcript_path=""
        )
        session.add(interview)
        session.commit()
    return PlainTextResponse("Session initialized")


@app.post("/upload")
async def upload(
    video: UploadFile = File(...),
    transcript: Optional[UploadFile] = File(None),  
    sessionId: str = Form(...),
    name: str = Form(...),
    email: str = Form(...)
):
    session_dir = os.path.join(UPLOAD_DIR, sessionId)
    os.makedirs(session_dir, exist_ok=True)

    video_path = os.path.join(session_dir, "interview_video.webm")
    with open(video_path, "wb") as f:
        shutil.copyfileobj(video.file, f)

    if transcript:
        transcript_path = os.path.join(session_dir, "interview_transcript.txt")
        with open(transcript_path, "wb") as f:
            shutil.copyfileobj(transcript.file, f)
        transcript_url = f"/uploads/{sessionId}/interview_transcript.txt"
    else:
        transcript_path = None
        transcript_url = ""

    interview = Interview(
        name=name,
        email=email,
        sessionId=sessionId,
        video_path=f"/uploads/{sessionId}/interview_video.webm",
        transcript_path=transcript_url
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

@app.post("/upload-chunk")
async def upload_chunk(
    chunk: UploadFile = File(...),
    sessionId: str = Form(...),
    index: int = Form(...)
):
    session_dir = os.path.join(UPLOAD_DIR, sessionId, "chunks")
    os.makedirs(session_dir, exist_ok=True)

    chunk_path = os.path.join(session_dir, f"chunk_{index:04d}.webm")
    with open(chunk_path, "wb") as f:
        shutil.copyfileobj(chunk.file, f)

    
    with open(os.path.join(session_dir, "last_modified.txt"), "w") as f:
        f.write(datetime.utcnow().isoformat())

    return PlainTextResponse(f"Chunk {index} received for session {sessionId}")

@app.post("/finalize-session")
def finalize_session(sessionId: str = Form(...), name: str = Form(...), email: str = Form(...)):
    session_dir = os.path.join(UPLOAD_DIR, sessionId)
    chunks_dir = os.path.join(session_dir, "chunks")
    output_video = os.path.join(session_dir, "interview_video.webm")

    # Merge chunks if video doesn't exist
    if not os.path.exists(output_video):
        chunk_files = sorted([f for f in os.listdir(chunks_dir) if f.endswith(".webm")])

        with open(output_video, "wb") as out:
            for filename in chunk_files:
                with open(os.path.join(chunks_dir, filename), "rb") as f:
                    shutil.copyfileobj(f, out)

    # Add to SQLite
    with Session(engine) as session:
        interview = Interview(
            name=name,
            email=email,
            sessionId=sessionId,
            video_path=f"/uploads/{sessionId}/interview_video.webm",
            transcript_path="",  # optional
        )
        session.add(interview)
        session.commit()

    return PlainTextResponse(f"Session {sessionId} finalized.")



@app.get("/")
def read_root():
    return {"message": "FastAPI backend with SQLite is live!"}

from datetime import timedelta

@app.post("/admin/finalize-stale-sessions")
def finalize_stale_sessions():
    cutoff = datetime.utcnow() - timedelta(minutes=3)

    for session_id in os.listdir(UPLOAD_DIR):
        chunks_dir = os.path.join(UPLOAD_DIR, session_id, "chunks")
        if not os.path.exists(chunks_dir):
            continue

        last_modified_file = os.path.join(chunks_dir, "last_modified.txt")
        output_video_path = os.path.join(UPLOAD_DIR, session_id, "interview_video.webm")

        if os.path.exists(output_video_path):
            continue  

        if os.path.exists(last_modified_file):
            with open(last_modified_file, "r") as f:
                last_time = datetime.fromisoformat(f.read().strip())
                if last_time < cutoff:
                    
                    chunk_files = sorted([f for f in os.listdir(chunks_dir) if f.endswith(".webm")])

                    with open(output_video_path, "wb") as out:
                        for file in chunk_files:
                            if file.endswith(".webm"):
                                with open(os.path.join(chunks_dir, file), "rb") as chunk:
                                    shutil.copyfileobj(chunk, out)

                    
                    with Session(engine) as db:
                        existing = db.exec(select(Interview).where(Interview.sessionId == session_id)).first()
                        if not existing:
    
                            name = "Unknown"
                            email = "Unknown"

                            interview = Interview(
                                name=name,
                                email=email,
                                sessionId=session_id,
                                video_path=f"/uploads/{session_id}/interview_video.webm",
                                transcript_path=""
                                )
                            db.add(interview)
                            db.commit()


    return {"message": "Checked and finalized stale sessions."}

@app.post("/admin/recover-unfinalized")
def recover_partial_interviews():
    recovered = []

    for sessionId in os.listdir(UPLOAD_DIR):
        session_dir = os.path.join(UPLOAD_DIR, sessionId)
        chunks_dir = os.path.join(session_dir, "chunks")
        final_video_path = os.path.join(session_dir, "interview_video.webm")

        
        if os.path.exists(final_video_path) or not os.path.exists(chunks_dir):
            continue

        chunk_files = sorted([f for f in os.listdir(chunks_dir) if f.endswith(".webm")])

        if not chunk_files:
            continue

        # Merge chunks
        with open(final_video_path, "wb") as out:
            for filename in chunk_files:
                with open(os.path.join(chunks_dir, filename), "rb") as f:
                    shutil.copyfileobj(f, out)

        
        with Session(engine) as db:
            session_info = db.exec(select(Interview).where(Interview.sessionId == sessionId)).first()
            name = session_info.name if session_info else "Unknown"
            email = session_info.email if session_info else "unknown@example.com"



        
        with Session(engine) as session:
            session_info = session.exec(select(Interview).where(Interview.sessionId == sessionId)).first()
            name = session_info.name if session_info else "Unknown"
            email = session_info.email if session_info else "unknown@example.com"

            interview = Interview(
                name=name,
                email=email,
                sessionId=sessionId,
                video_path=f"/uploads/{sessionId}/interview_video.webm",
                transcript_path="",
                )
            session.add(interview)
            session.commit()


        recovered.append(sessionId)

    return {"recovered_sessions": recovered}

def finalize_stale_sessions_logic():
    cutoff = datetime.utcnow() - timedelta(minutes=3)

    for session_id in os.listdir(UPLOAD_DIR):
        chunks_dir = os.path.join(UPLOAD_DIR, session_id, "chunks")
        if not os.path.exists(chunks_dir):
            continue

        last_modified_file = os.path.join(chunks_dir, "last_modified.txt")
        output_video_path = os.path.join(UPLOAD_DIR, session_id, "interview_video.webm")

        if os.path.exists(output_video_path):
            continue  # already finalized

        if os.path.exists(last_modified_file):
            with open(last_modified_file, "r") as f:
                last_time = datetime.fromisoformat(f.read().strip())
                if last_time < cutoff:
                    chunk_files = sorted([f for f in os.listdir(chunks_dir) if f.endswith(".webm")])

                    with open(output_video_path, "wb") as out:
                        for file in chunk_files:
                            if file.endswith(".webm"):
                                with open(os.path.join(chunks_dir, file), "rb") as chunk:
                                    shutil.copyfileobj(chunk, out)

                    with Session(engine) as db:
                        existing = db.exec(select(Interview).where(Interview.sessionId == session_id)).first()
                        if not existing:
                            interview = Interview(
                                name="Unknown",
                                email="Unknown",
                                sessionId=session_id,
                                video_path=f"/uploads/{session_id}/interview_video.webm",
                                transcript_path=""
                            )
                            db.add(interview)
                            db.commit()


@app.on_event("startup")
@repeat_every(seconds=60)  
def auto_finalize_stale_sessions_task():
    print("⏳ Auto-finalizing stale sessions...")
    finalize_stale_sessions_logic()




