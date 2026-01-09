from pydantic import BaseModel, EmailStr, Field
from typing import Optional

class AdminLoginRequest(BaseModel):
    email: str
    password: str

class QuestionCreate(BaseModel):
    subject: Optional[str] = None
    question: str
    section_id: Optional[int] = None
    rating_3_text: Optional[str] = None
    rating_neg3_text: Optional[str] = None
    positive_rating_text: Optional[str] = None  # Alias for rating_3_text
    negative_rating_text: Optional[str] = None  # Alias for rating_neg3_text
    show_rating_scale: Optional[bool] = True  # Whether to show rating scale (default True)

class QuestionUpdate(BaseModel):
    question: Optional[str] = None
    section_id: Optional[int] = None
    rating_3_text: Optional[str] = None
    rating_neg3_text: Optional[str] = None
    positive_rating_text: Optional[str] = None  # Alias for rating_3_text
    negative_rating_text: Optional[str] = None  # Alias for rating_neg3_text
    show_rating_scale: Optional[bool] = None  # Whether to show rating scale

class SectionCreate(BaseModel):
    label: str
    title: str
    company_id: Optional[int] = None

class SectionUpdate(BaseModel):
    label: Optional[str] = None
    title: Optional[str] = None
    company_id: Optional[int] = None

class AnswerCreate(BaseModel):
    answer: str
    rating: Optional[int] = Field(None, ge=-3, le=3)

class AnswerSubmit(BaseModel):
    question_id: int
    answer: str
    rating: Optional[int] = Field(None, ge=-3, le=3)
    submitted_at: Optional[str] = None

class UserCreate(BaseModel):
    email: EmailStr
    name: str
    password: str
    company_id: Optional[int] = None

class UserLogin(BaseModel):
    email: EmailStr
    password: str
