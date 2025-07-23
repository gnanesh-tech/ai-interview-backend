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
