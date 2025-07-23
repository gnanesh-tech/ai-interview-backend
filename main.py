from fastapi import FastAPI, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import SQLModel, Field, Session, create_engine, select
from datetime import datetime
from fastapi import Request
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
@app.post("/upload-chunk")
async def upload_chunk(
    chunk: UploadFile = File(...),
    sessionId: str = Form(...)
):
    session_dir = os.path.join(UPLOAD_DIR, sessionId)
    os.makedirs(session_dir, exist_ok=True)

    # Count existing chunks to give next chunk a number
    existing_chunks = sorted([
        f for f in os.listdir(session_dir)
        if f.endswith("_chunk.webm")
    ])
    chunk_index = len(existing_chunks) + 1
    chunk_filename = f"{chunk_index:04d}_chunk.webm"

    chunk_path = os.path.join(session_dir, chunk_filename)
    with open(chunk_path, "wb") as f:
        shutil.copyfileobj(chunk.file, f)

    return PlainTextResponse("Chunk stored.")



@app.get("/admin/uploads")
def list_uploaded_sessions(request: Request):
    with Session(engine) as session:
        interviews = session.exec(select(Interview)).all()
        data = {}

        for i in interviews:
            session_dir = os.path.join(UPLOAD_DIR, i.sessionId)
            full_video = os.path.join(session_dir, "interview_video.webm")
            partial_chunks = sorted([
                f for f in os.listdir(session_dir)
                if f.endswith("_chunk.webm")
            ])

            # Set default
            video_file = i.video_path

            if not os.path.exists(full_video) and partial_chunks:
    # Merge chunks into a temporary playable file
                merged_filename = "partial_interview.webm"
                merged_path = os.path.join(session_dir, merged_filename)

                with open(merged_path, "wb") as outfile:
                    for chunk_name in partial_chunks:
                        chunk_path = os.path.join(session_dir, chunk_name)
                        with open(chunk_path, "rb") as infile:
                            shutil.copyfileobj(infile, outfile)

                video_file = f"/uploads/{i.sessionId}/{merged_filename}"




@app.get("/")
def read_root():
    return {"message": "FastAPI backend with SQLite is live!"}
