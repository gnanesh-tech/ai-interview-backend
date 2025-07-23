from fastapi import FastAPI, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
from sqlmodel import SQLModel, Field, Session, create_engine, select
from datetime import datetime
import subprocess
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

    
    video_path = os.path.join(session_dir, "interview_video.webm")
    with open(video_path, "wb") as f:
        shutil.copyfileobj(video.file, f)

    
    transcript_path = os.path.join(session_dir, "interview_transcript.txt")
    with open(transcript_path, "wb") as f:
        shutil.copyfileobj(transcript.file, f)

    
    interview = Interview(
        name=name,
        email=email,
        sessionId=sessionId,
        video_path=f"/uploads/{sessionId}/interview_video.webm",
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

MERGE_TIMEOUT = timedelta(minutes=2)

scheduler = BackgroundScheduler()


@app.on_event("startup")
def on_startup():
    SQLModel.metadata.create_all(engine)
    scheduler.add_job(check_and_merge_stale, "interval", minutes=1)
    scheduler.start()

@app.on_event("shutdown")
def on_shutdown():
    scheduler.shutdown()

def check_and_merge_stale():
    """Merge chunked sessions if no new chunks added recently."""
    for session_id in os.listdir(UPLOAD_DIR):
        session_chunks = os.path.join(UPLOAD_DIR, session_id, "chunks")
        if not os.path.isdir(session_chunks):
            continue

        # get most recent chunk-modified time
        times = [os.path.getmtime(os.path.join(session_chunks, f))
                 for f in os.listdir(session_chunks)]
        if not times: continue

        if datetime.now().timestamp() - max(times) > MERGE_TIMEOUT.total_seconds():
            try:
                # trigger our existing merge logic
                merge_chunks(sessionId=session_id)
            except Exception:
                pass  # swallow errors
    




@app.post("/merge-chunks")
def merge_chunks(sessionId: str = Form(...)):
    session_dir = os.path.join(UPLOAD_DIR, sessionId)
    if not os.path.exists(session_dir):
        return JSONResponse(content={"error": "Session not found"}, status_code=404)

    # Step 1: List and sort chunk files
    chunk_files = sorted([f for f in os.listdir(session_dir) if f.startswith("chunk_") and f.endswith(".webm")])

    if not chunk_files:
        return JSONResponse(content={"error": "No chunks found"}, status_code=404)

    # Step 2: Create a temporary file list for ffmpeg
    file_list_path = os.path.join(session_dir, "file_list.txt")
    with open(file_list_path, "w") as f:
        for chunk in chunk_files:
            f.write(f"file '{os.path.join(session_dir, chunk)}'\n")

    
    


    # Step 3: Run ffmpeg to merge
    output_path = "merged_interview.webm"
    try:
        subprocess.run([
            "ffmpeg", "-f", "concat", "-safe", "0", "-i", "file_list.txt",
            "-c", "copy", output_path
        ], check=True)
    except subprocess.CalledProcessError:
        return JSONResponse(content={"error": "Failed to merge chunks"}, status_code=500)

    return JSONResponse(content={"message": "Chunks merged successfully", "merged_video": f"/uploads/{sessionId}/merged_interview.webm"})
    # Update DB
    with Session(engine) as session:
        existing = session.exec(select(Interview).where(Interview.sessionId == sessionId)).first()
        if not existing:
            interview = Interview(
            name="(AutoRecovered)",
            email="(unknown)",
            sessionId=sessionId,
            video_path=f"/uploads/{sessionId}/merged_interview.webm",
            transcript_path="(none)"
        )
        session.add(interview)
        session.commit()


@app.post("/upload_chunk")
async def upload_chunk(
    chunk: UploadFile = File(...),
    sessionId: str = Form(...),
    chunkIndex: int = Form(...)
):
    chunk_dir = os.path.join(UPLOAD_DIR, sessionId, "chunks")
    os.makedirs(chunk_dir, exist_ok=True)

    chunk_filename = os.path.join(chunk_dir, f"chunk_{chunkIndex:04d}.webm")
    with open(chunk_filename, "wb") as f:
        shutil.copyfileobj(chunk.file, f)

    # Auto-merge if at least 10 chunks uploaded
    chunk_files = sorted([f for f in os.listdir(chunk_dir) if f.endswith(".webm")])
    if len(chunk_files) >= 5:
        merge_chunks_auto(sessionId)

    return PlainTextResponse(f"Chunk {chunkIndex} uploaded successfully.")

def merge_chunks_auto(sessionId: str):
    chunk_dir = os.path.join(UPLOAD_DIR, sessionId, "chunks")
    session_dir = os.path.join(UPLOAD_DIR, sessionId)
    os.makedirs(session_dir, exist_ok=True)

    chunk_files = sorted([f for f in os.listdir(chunk_dir) if f.endswith(".webm")])
    if not chunk_files:
        return

    file_list_path = os.path.join(chunk_dir, "file_list.txt")
    with open(file_list_path, "w") as f:
        for chunk in chunk_files:
            f.write(f"file '{os.path.join(chunk_dir, chunk)}'\n")

    merged_path = os.path.join(session_dir, "merged_interview.webm")

    try:
        subprocess.run([
            "ffmpeg", "-f", "concat", "-safe", "0", "-i", file_list_path,
            "-c", "copy", merged_path
        ], check=True)
    except subprocess.CalledProcessError as e:
        print("FFmpeg merge failed:", e)
        return

    # Update DB: create entry if not already present
    with Session(engine) as session:
        existing = session.exec(select(Interview).where(Interview.sessionId == sessionId)).first()
        if not existing:
            interview = Interview(
                name="(Incomplete)",
                email="(unknown)",
                sessionId=sessionId,
                video_path=f"/uploads/{sessionId}/merged_interview.webm",
                transcript_path="(none)"
            )
            session.add(interview)
            session.commit()



