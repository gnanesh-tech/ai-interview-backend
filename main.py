from fastapi import FastAPI, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
import os
import shutil

# 1. Initialize FastAPI
app = FastAPI()

# 2. CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_methods=["*"],
    allow_headers=["*"],
)

# 3. Set up upload directory
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 4. Mount uploads directory as static files BEFORE routes
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# 5. Questions endpoint
@app.get("/questions")
def get_questions():
    return [
        "Tell me about yourself.",
        "What are your strengths and weaknesses?",
        "Why do you want to join our company?",
        "Describe a challenge you faced and how you handled it.",
        "Where do you see yourself in five years?"
    ]

# 6. Upload endpoint
@app.post("/upload")
async def upload(
    video: UploadFile = File(...),
    transcript: UploadFile = File(...),
    sessionId: str = Form(...)
):
    session_dir = os.path.join(UPLOAD_DIR, sessionId)
    os.makedirs(session_dir, exist_ok=True)

    # Save video
    with open(os.path.join(session_dir, "interview_video.webm"), "wb") as f:
        shutil.copyfileobj(video.file, f)

    # Save transcript
    with open(os.path.join(session_dir, "interview_transcript.txt"), "wb") as f:
        shutil.copyfileobj(transcript.file, f)

    return PlainTextResponse(f"Files uploaded successfully for session: {sessionId}")

# 7. Root route
@app.get("/")
def read_root():
    return {"message": "FastAPI backend is live!"}

# 8. Admin uploads listing
@app.get("/admin/uploads")
def list_uploaded_sessions():
    sessions = {}
    for session_id in os.listdir(UPLOAD_DIR):
        session_path = os.path.join(UPLOAD_DIR, session_id)
        if os.path.isdir(session_path):
            video_file = os.path.join(session_path, "interview_video.webm")
            transcript_file = os.path.join(session_path, "interview_transcript.txt")
            if os.path.exists(video_file) and os.path.exists(transcript_file):
                sessions[session_id] = {
                    "video": f"/uploads/{session_id}/interview_video.webm",
                    "transcript": f"/uploads/{session_id}/interview_transcript.txt"
                }
    return JSONResponse(content=sessions)
