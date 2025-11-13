"""
Database Schemas

Define your MongoDB collection schemas here using Pydantic models.
These schemas are used for data validation in your application.

Each Pydantic model represents a collection in your database.
Model name is converted to lowercase for the collection name:
- User -> "user" collection
- Product -> "product" collection
- BlogPost -> "blogs" collection
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import datetime

# Core app schemas for Smart Alarm

TaskType = Literal["photo", "puzzle", "steps"]

class Alarm(BaseModel):
    """
    Alarm configuration per user
    Collection name: "alarm"
    """
    user_id: str = Field(..., description="User identifier")
    alarm_label: Optional[str] = Field(None, description="Optional label for the alarm")
    alarm_time: str = Field(..., description="Alarm time in HH:MM (24h) format")
    apps: List[str] = Field(default_factory=list, description="App bundle names to lock when missed")
    lock_duration_minutes: int = Field(30, ge=5, le=1440, description="How long to keep apps locked")
    task_type: TaskType = Field("puzzle", description="Unlock task type")

class LockEvent(BaseModel):
    """
    Lock event generated when an alarm is missed
    Collection name: "lockevent"
    """
    user_id: str
    apps: List[str]
    task_type: TaskType
    unlocked: bool = False
    expires_at: datetime
    alarm_id: Optional[str] = None
    # Task payloads (optional depending on type)
    puzzle_question: Optional[str] = None
    puzzle_answer: Optional[str] = None
    steps_target: Optional[int] = None
    photo_required: Optional[bool] = None

class TaskAttempt(BaseModel):
    """
    Records unlock attempts and outcomes
    Collection name: "taskattempt"
    """
    lock_id: str
    user_id: str
    task_type: TaskType
    success: bool
    details: Optional[str] = None

# Example schemas (kept for reference)
class User(BaseModel):
    name: str
    email: str
    is_active: bool = True

class Product(BaseModel):
    title: str
    description: Optional[str] = None
    price: float
    category: str
    in_stock: bool = True
