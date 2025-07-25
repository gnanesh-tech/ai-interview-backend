import shutil
import os
from datetime import datetime, timedelta
from fastapi import FastAPI, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import SQLModel, Field, Session, create_engine, select
from fastapi_utils.tasks import repeat_every

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

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
    return [ ... ]  # same as before

@app.post("/start-session")
def start_session(sessionId: str = Form(...), name: str = Form(...), email: str = Form(...)):
    with Session(engine) as session:
        existing = session.exec(select(Interview).where(Interview.sessionId == sessionId)).first()
        if existing:
            return PlainTextResponse("Session already initialized", status_code=200)
        interview = Interview(
            name=name, email=email, sessionId=sessionId,
            video_path="", transcript_path=""
        )
        session.add(interview)
        session.commit()
    return PlainTextResponse("Session initialized")

@app.post("/upload-chunk")
async def upload_chunk(chunk: UploadFile = File(...), sessionId: str = Form(...), index: int = Form(...)):
    session_dir = os.path.join(UPLOAD_DIR, sessionId, "chunks")
    os.makedirs(session_dir, exist_ok=True)
    chunk_path = os.path.join(session_dir, f"chunk_{index:04d}.webm")
    with open(chunk_path, "wb") as f:
        shutil.copyfileobj(chunk.file, f)
    with open(os.path.join(session_dir, "last_modified.txt"), "w") as f:
        f.write(datetime.utcnow().isoformat())
    return PlainTextResponse(f"Chunk {index} received for session {sessionId}")

@app.post("/finalize-session")
def finalize_session(sessionId: str = Form(...), name: str = Form(...), email: str = Form(...),
                     transcript: str = Form("")):
    session_dir = os.path.join(UPLOAD_DIR, sessionId)
    chunks_dir = os.path.join(session_dir, "chunks")
    out_path = os.path.join(session_dir, "interview_video.webm")
    if os.path.exists(chunks_dir) and not os.path.exists(out_path):
        chunk_files = sorted(os.listdir(chunks_dir))
        with open(out_path, "wb") as out:
            for fname in chunk_files:
                if fname.endswith(".webm"):
                    with open(os.path.join(chunks_dir, fname), "rb") as cf:
                        shutil.copyfileobj(cf, out)
    with Session(engine) as session:
        interview = Interview(
            name=name or "Unknown", email=email or "Unknown",
            sessionId=sessionId,
            video_path=f"/uploads/{sessionId}/interview_video.webm",
            transcript_path=""  # you may store transcript separately
        )
        session.add(interview)
        session.commit()
    return PlainTextResponse(f"Session {sessionId} finalized.")

@app.get("/admin/uploads")
def list_uploaded_sessions():
    with Session(engine) as session:
        interviews = session.exec(select(Interview)).all()
    return JSONResponse({ i.sessionId: {
            "name": i.name, "email": i.email,
            "video": i.video_path, "transcript": i.transcript_path,
            "timestamp": i.timestamp.isoformat()
        } for i in interviews })

def finalize_stale_sessions_logic():
    cutoff = datetime.utcnow() - timedelta(minutes=3)
    for sid in os.listdir(UPLOAD_DIR):
        chunks_dir = os.path.join(UPLOAD_DIR, sid, "chunks")
        final_vid = os.path.join(UPLOAD_DIR, sid, "interview_video.webm")
        if not os.path.exists(chunks_dir) or os.path.exists(final_vid):
            continue
        last_mod = os.path.join(chunks_dir, "last_modified.txt")
        if os.path.exists(last_mod):
            lm = datetime.fromisoformat(open(last_mod).read().strip())
            if lm < cutoff:
                chunk_files = sorted(os.listdir(chunks_dir))
                with open(final_vid, "wb") as out:
                    for fn in chunk_files:
                        if fn.endswith(".webm"):
                            with open(os.path.join(chunks_dir, fn), "rb") as cf:
                                shutil.copyfileobj(cf, out)
                with Session(engine) as session:
                    exists = session.exec(select(Interview).where(Interview.sessionId==sid)).first()
                    if not exists:
                        interview = Interview(
                            name="Unknown", email="Unknown",
                            sessionId=sid, video_path=f"/uploads/{sid}/interview_video.webm",
                            transcript_path=""
                        )
                        session.add(interview)
                        session.commit()

@app.on_event("startup")
@repeat_every(seconds=60)
def auto_finalize_stale_sessions_task():
    finalize_stale_sessions_logic()
