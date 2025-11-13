import os
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Literal

from database import db, create_document, get_documents

app = FastAPI(title="Smart Alarm API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic DTOs for requests
TaskType = Literal["photo", "puzzle", "steps"]

class AlarmCreate(BaseModel):
    user_id: str
    alarm_label: Optional[str] = None
    alarm_time: str  # HH:MM 24h
    apps: List[str] = []
    lock_duration_minutes: int = 30
    task_type: TaskType = "puzzle"

class AlarmOut(BaseModel):
    id: str
    user_id: str
    alarm_label: Optional[str]
    alarm_time: str
    apps: List[str]
    lock_duration_minutes: int
    task_type: TaskType

class LockEventOut(BaseModel):
    id: str
    user_id: str
    apps: List[str]
    task_type: TaskType
    unlocked: bool
    expires_at: str
    alarm_id: Optional[str]
    puzzle_question: Optional[str] = None
    steps_target: Optional[int] = None
    photo_required: Optional[bool] = None

class AttemptIn(BaseModel):
    lock_id: str
    user_id: str
    task_type: TaskType
    answer: Optional[str] = None
    steps: Optional[int] = None

@app.get("/")
def root():
    return {"message": "Smart Alarm Backend is running"}

@app.get("/schema")
def get_schema_info():
    # Expose schemas for tooling (no strict validation here)
    return {"collections": ["alarm", "lockevent", "taskattempt", "user", "product"]}

# Helpers

def _object_to_out(doc: dict) -> dict:
    doc = {**doc}
    if "_id" in doc:
        doc["id"] = str(doc.pop("_id"))
    # Convert datetimes to ISO
    for key in ["created_at", "updated_at", "expires_at"]:
        if key in doc and isinstance(doc[key], datetime):
            doc[key] = doc[key].astimezone(timezone.utc).isoformat()
    return doc

# Endpoints

@app.post("/alarms", response_model=AlarmOut)
def create_alarm(payload: AlarmCreate):
    # Basic validation
    if ":" not in payload.alarm_time:
        raise HTTPException(status_code=400, detail="alarm_time must be HH:MM")
    alarm_dict = payload.model_dump()
    from schemas import Alarm as AlarmSchema  # for type alignment
    alarm_id = create_document("alarm", AlarmSchema(**alarm_dict))
    # Fetch saved to return id
    saved = db["alarm"].find_one({"_id": db["alarm"].ObjectId if False else {}})
    # simpler: read back by id
    from bson import ObjectId
    saved = db["alarm"].find_one({"_id": ObjectId(alarm_id)})
    return _object_to_out(saved)

@app.get("/alarms", response_model=List[AlarmOut])
def list_alarms(user_id: Optional[str] = None):
    filt = {"user_id": user_id} if user_id else {}
    docs = get_documents("alarm", filt)
    return [_object_to_out(d) for d in docs]

@app.post("/locks/simulate", response_model=LockEventOut)
def simulate_lock(user_id: str, alarm_id: Optional[str] = None, task_type: TaskType = "puzzle", lock_minutes: int = 30):
    # Create a simulated lock event when an alarm is missed
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=lock_minutes)

    # Create task payloads
    puzzle_question = None
    steps_target = None
    photo_required = None

    if task_type == "puzzle":
        # simple math puzzle
        import random
        a, b = random.randint(10, 99), random.randint(10, 99)
        puzzle_question = f"What is {a} + {b}?"
        puzzle_answer = str(a + b)
    elif task_type == "steps":
        steps_target = 30  # sample target
        puzzle_answer = None
    else:  # photo
        photo_required = True
        puzzle_answer = None

    lock_doc = {
        "user_id": user_id,
        "apps": [],
        "task_type": task_type,
        "unlocked": False,
        "expires_at": expires_at,
        "alarm_id": alarm_id,
        "puzzle_question": puzzle_question,
        "puzzle_answer": puzzle_answer,
        "steps_target": steps_target,
        "photo_required": photo_required,
    }

    lock_id = create_document("lockevent", lock_doc)
    from bson import ObjectId
    saved = db["lockevent"].find_one({"_id": ObjectId(lock_id)})
    out = _object_to_out(saved)
    # do not expose puzzle_answer
    if "puzzle_answer" in out:
        out.pop("puzzle_answer")
    return out

@app.post("/locks/attempt")
def attempt_unlock(payload: AttemptIn):
    from bson import ObjectId
    lock = db["lockevent"].find_one({"_id": ObjectId(payload.lock_id)})
    if not lock:
        raise HTTPException(status_code=404, detail="Lock not found")
    if lock.get("unlocked"):
        return {"status": "already_unlocked"}

    success = False
    detail = ""

    if payload.task_type == "puzzle":
        provided = (payload.answer or "").strip()
        correct = str(lock.get("puzzle_answer", "")).strip()
        success = provided == correct
        detail = "correct" if success else "incorrect"
    elif payload.task_type == "steps":
        needed = int(lock.get("steps_target", 0))
        success = int(payload.steps or 0) >= needed
        detail = f"{payload.steps or 0}/{needed} steps"
    else:
        # photo verification is mocked as success when any answer provided
        success = bool(payload.answer)
        detail = "photo accepted" if success else "photo missing"

    # Record attempt
    attempt_doc = {
        "lock_id": payload.lock_id,
        "user_id": payload.user_id,
        "task_type": payload.task_type,
        "success": success,
        "details": detail,
    }
    create_document("taskattempt", attempt_doc)

    if success:
        db["lockevent"].update_one({"_id": ObjectId(payload.lock_id)}, {"$set": {"unlocked": True, "updated_at": datetime.now(timezone.utc)}})
        return {"status": "unlocked"}
    else:
        return {"status": "try_again", "detail": detail}

@app.get("/insights/morning")
def morning_insights(user_id: str):
    # Basic insights: total locks, success rate, avg attempts
    total_locks = db["lockevent"].count_documents({"user_id": user_id})
    unlocked = db["lockevent"].count_documents({"user_id": user_id, "unlocked": True})
    attempts = list(db["taskattempt"].find({"user_id": user_id}))
    attempts_count = len(attempts)
    attempts_per_lock = (attempts_count / total_locks) if total_locks else 0

    return {
        "total_locks": total_locks,
        "unlocked": unlocked,
        "success_rate": (unlocked / total_locks) if total_locks else 0,
        "avg_attempts_per_lock": attempts_per_lock,
    }

@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
    return response

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
