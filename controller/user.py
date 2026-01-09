from fastapi import APIRouter, HTTPException, Depends, Body
from sqlalchemy.orm import Session
from database.models import UserAnswer, Question, User, Company, Profile, Section
from .basemodel import AnswerCreate, AnswerSubmit, QuestionCreate, AdminLoginRequest, UserCreate, UserLogin
from typing import List
from database.database import get_db
from auth import get_password_hash, verify_password, create_access_token, decode_token
from fastapi.security import OAuth2PasswordBearer
from pydantic import EmailStr
import random
import smtplib
import time
import os
from dotenv import load_dotenv
from email.mime.text import MIMEText
import uuid

router = APIRouter()
load_dotenv()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/user/login")

reset_codes = {}  
OTP_EXPIRATION_SECONDS = 300  

@router.post("/signup")
def signup(user: UserCreate, db: Session = Depends(get_db)):
    # Check if profile already exists
    db_profile = db.query(Profile).filter(Profile.email == user.email).first()
    if db_profile:
        raise HTTPException(status_code=400, detail="Email already registered")

    # Validate company_id if provided
    if user.company_id is not None:
        company = db.query(Company).filter(Company.id == user.company_id).first()
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")

    # Create profile with UUID (in Supabase, this would come from auth.users)
    # For now, generate a UUID - in production, this should come from Supabase auth
    profile_id = uuid.uuid4()
    new_profile = Profile(
        id=profile_id,
        email=user.email, 
        name=user.name,
        company_id=user.company_id
    )
    db.add(new_profile)
    db.commit()
    db.refresh(new_profile)

    return {"message": "User created successfully", "profile_id": str(profile_id)}

@router.post("/login")
def login(user: UserLogin, db: Session = Depends(get_db)):
    # Try Profile first (main user table), fallback to User (admin/internal)
    db_profile = db.query(Profile).filter(Profile.email == user.email).first()
    db_user = db.query(User).filter(User.email == user.email).first()
    
    # For Profile, we'd typically use Supabase auth, but for now check User table for password
    # In production with Supabase, Profile login would be handled by Supabase auth
    if db_user and verify_password(user.password, db_user.hashed_password):
        access_token = create_access_token(data={"sub": db_user.email})
        return {"access_token": access_token, "token_type": "bearer"}
    
    # If profile exists but no User record, this is a Supabase auth user
    # In production, handle Supabase auth token validation here
    if db_profile:
        # For now, create a token (in production, validate Supabase JWT)
        access_token = create_access_token(data={"sub": db_profile.email, "profile_id": str(db_profile.id)})
        return {"access_token": access_token, "token_type": "bearer"}
    
    raise HTTPException(status_code=401, detail="Invalid email or password")

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        email = decode_token(token)
        # Try Profile first (main user table)
        profile = db.query(Profile).filter(Profile.email == email).first()
        if profile:
            return profile
        # Fallback to User (admin/internal)
        user = db.query(User).filter(User.email == email).first()
        if user:
            return user
        raise HTTPException(status_code=404, detail="User not found")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")

@router.get("/get-companies")
def get_companies(db: Session = Depends(get_db)):
    """Get all companies for user signup"""
    companies = db.query(Company).order_by(Company.name.asc()).all()
    return [{"id": company.id, "name": company.name} for company in companies]

@router.get("/get-questions")
def get_questions(db: Session = Depends(get_db)):
    return db.query(Question).all()

@router.get("/get-question/")
def get_question(current_user = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get questions grouped by sections for the current user's company"""
    try:
        # Get user's company_id
        if isinstance(current_user, User):
            company_id = current_user.company_id
        else:
            # Profile user
            company_id = current_user.company_id
        
        # Get sections for this company AND global sections (company_id = null)
        # Global sections should be available to all users
        if company_id is not None:
            # Include both company-specific sections and global sections (null company_id)
            from sqlalchemy import or_
            sections = db.query(Section).filter(
                or_(
                    Section.company_id == company_id,
                    Section.company_id.is_(None)  # Global sections available to all
                )
            ).order_by(Section.label).all()
        else:
            # If user has no company, return all sections (including global ones)
            sections = db.query(Section).order_by(Section.label).all()
        
        if not sections:
            return {"sections": []}
        
        result = []
        for section in sections:
            questions = db.query(Question).filter(Question.section_id == section.id).all()
            
            # Get user's answers for these questions
            user_id = current_user.id
            if isinstance(current_user, User):
                # User table uses integer ID, but user_answers uses UUID (Profile)
                # Skip answers for User accounts
                user_answers = {}
            else:
                # Profile uses UUID
                answers = db.query(UserAnswer).filter(
                    UserAnswer.user_id == user_id,
                    UserAnswer.question_id.in_([q.id for q in questions])
                ).all()
                user_answers = {a.question_id: a for a in answers}
            
            section_data = {
                "section_id": section.id,
                "label": section.label or "",
                "title": section.title or "",
                "questions": []
            }
            
            for question in questions:
                answer = user_answers.get(question.id)
                question_data = {
                    "question_id": question.id,
                    "question": question.question or "",
                    "rating_3_text": question.rating_3_text or "",
                    "rating_neg3_text": question.rating_neg3_text or "",
                    "show_rating_scale": getattr(question, 'show_rating_scale', True),  # Default to True for backward compatibility
                    "answer": answer.answer if answer else None,
                    "rating": answer.rating if answer else None,
                }
                section_data["questions"].append(question_data)
            
            result.append(section_data)
        
        return {"sections": result}
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"Error in get_question: {str(e)}")
        print(f"Traceback: {error_trace}")
        raise HTTPException(status_code=500, detail=f"Error fetching questions: {str(e)}")

@router.post("/submit-answer/")
def submit_answers(answers: List[AnswerSubmit], current_user = Depends(get_current_user), db: Session = Depends(get_db)):
    """Submit multiple answers at once (matches frontend API)"""
    from datetime import datetime
    
    # Get user_id - handle both Profile (uuid) and User (int) types
    user_id = current_user.id
    if isinstance(current_user, User):
        # If it's a User (int), we need to find or create a Profile
        # For now, raise error - User table is for admin/internal use
        raise HTTPException(status_code=400, detail="Please use Profile account to submit answers")
    
    saved_answers = []
    
    for answer_data in answers:
        # Validate question exists
        db_question = db.query(Question).filter(Question.id == answer_data.question_id).first()
        if not db_question:
            continue  # Skip invalid question_id
        
        # Parse submitted_at if provided
        submitted_at = None
        if answer_data.submitted_at:
            try:
                # Try ISO format first
                submitted_at = datetime.fromisoformat(answer_data.submitted_at.replace('Z', '+00:00'))
            except:
                try:
                    # Try parsing as string
                    submitted_at = datetime.fromisoformat(answer_data.submitted_at)
                except:
                    submitted_at = datetime.now()
        else:
            submitted_at = datetime.now()
        
        # Check if answer already exists
        db_answer = db.query(UserAnswer).filter(
            UserAnswer.user_id == user_id,
            UserAnswer.question_id == answer_data.question_id
        ).first()
        
        if db_answer:
            # Update existing answer
            db_answer.answer = answer_data.answer
            db_answer.rating = answer_data.rating
            db_answer.submitted_at = submitted_at
            answer_id = db_answer.id
        else:
            # Create new answer
            db_answer = UserAnswer(
                question_id=answer_data.question_id,
                user_id=user_id,
                answer=answer_data.answer,
                feedback=None,
                feedback_generated=False,
                rating=answer_data.rating,
                submitted_at=submitted_at
            )
            db.add(db_answer)
            db.flush()  # Flush to get the ID
            answer_id = db_answer.id
        
        saved_answers.append({
            "question_id": answer_data.question_id,
            "answer_id": answer_id
        })
    
    db.commit()
    
    return {
        "message": f"Successfully saved {len(saved_answers)} answer(s)",
        "answers": saved_answers
    }

@router.post("/submit-answer/{question_id}/")
def submit_answer(question_id: int, answer: AnswerCreate, current_user = Depends(get_current_user), db: Session = Depends(get_db)):
    """Submit a single answer (legacy endpoint)"""
    from datetime import datetime
    
    db_question = db.query(Question).filter(Question.id == question_id).first()

    if not db_question:
        raise HTTPException(status_code=404, detail="Question not found")

    # Get user_id - handle both Profile (uuid) and User (int) types
    user_id = current_user.id
    if isinstance(current_user, User):
        # If it's a User (int), we need to find or create a Profile
        # For now, raise error - User table is for admin/internal use
        raise HTTPException(status_code=400, detail="Please use Profile account to submit answers")

    db_answer = db.query(UserAnswer).filter(
        UserAnswer.user_id == user_id,
        UserAnswer.question_id == question_id
    ).first()

    if db_answer:
        db_answer.answer = answer.answer
        db_answer.rating = answer.rating
        db_answer.submitted_at = datetime.now()  # Update timestamp on edit
    else:
        db_answer = UserAnswer(
            question_id=question_id,
            user_id=user_id,
            answer=answer.answer,
            feedback=None,
            feedback_generated=False,
            rating=answer.rating,
            submitted_at=datetime.now()  # Set timestamp on creation
        )
        db.add(db_answer)

    db.commit()
    db.refresh(db_answer)

    return {
        "message": "Answer saved successfully",
        "answer_id": db_answer.id,
        "rating": db_answer.rating,
        "submitted_at": db_answer.submitted_at.isoformat() if db_answer.submitted_at else None
    }

@router.get("/get-user-answers")
def get_user_answers(current_user = Depends(get_current_user), db: Session = Depends(get_db)):
    user_id = current_user.id
    if isinstance(current_user, User):
        raise HTTPException(status_code=400, detail="Please use Profile account to view answers")
    
    answers = db.query(UserAnswer).filter(UserAnswer.user_id == user_id).all()
    return [{
        "question_id": a.question_id,
        "answer": a.answer,
        "rating": a.rating
    } for a in answers]

@router.post("/forgot-password")
def forgot_password(email: EmailStr = Body(...), db: Session = Depends(get_db)):
    # Check both Profile and User tables
    profile = db.query(Profile).filter(Profile.email == email).first()
    user = db.query(User).filter(User.email == email).first()
    if not profile and not user:
        raise HTTPException(status_code=404, detail="User not found")

    otp = random.randint(1000, 9999)
    reset_codes[email] = {"otp": str(otp), "timestamp": time.time()}

    smtp_email = os.getenv("SMTP_EMAIL")
    smtp_password = os.getenv("SMTP_PASSWORD")
    
    if not smtp_email or not smtp_password:
        raise HTTPException(status_code=500, detail="SMTP credentials not configured")

    msg = MIMEText(f"Your password reset verification code is: {otp}")
    msg["Subject"] = "Password Reset Code"
    msg["From"] = smtp_email
    msg["To"] = email

    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(smtp_email, smtp_password)
            server.send_message(msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")

    return {"message": "Verification code sent to email."}

@router.post("/resend-otp")
def resend_otp(email: EmailStr = Body(...), db: Session = Depends(get_db)):
    # Check both Profile and User tables
    profile = db.query(Profile).filter(Profile.email == email).first()
    user = db.query(User).filter(User.email == email).first()
    if not profile and not user:
        raise HTTPException(status_code=404, detail="User not found")

    otp = random.randint(1000, 9999)
    reset_codes[email] = {"otp": str(otp), "timestamp": time.time()}

    smtp_email = os.getenv("SMTP_EMAIL")
    smtp_password = os.getenv("SMTP_PASSWORD")
    
    if not smtp_email or not smtp_password:
        raise HTTPException(status_code=500, detail="SMTP credentials not configured")

    msg = MIMEText(f"Your new password reset verification code is: {otp}")
    msg["Subject"] = "Resent Password Reset Code"
    msg["From"] = smtp_email
    msg["To"] = email

    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(smtp_email, smtp_password)
            server.send_message(msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to resend email: {str(e)}")

    return {"message": "Verification code resent to email."}

@router.post("/reset-password")
def reset_password(email: EmailStr = Body(...), code: str = Body(...), new_password: str = Body(...), db: Session = Depends(get_db)):
    record = reset_codes.get(email)
    if not record:
        raise HTTPException(status_code=400, detail="No reset request found")

    if time.time() - record["timestamp"] > OTP_EXPIRATION_SECONDS:
        reset_codes.pop(email)
        raise HTTPException(status_code=400, detail="Verification code expired")

    if record["otp"] != code:
        raise HTTPException(status_code=400, detail="Invalid verification code")

    # Check both Profile and User tables
    profile = db.query(Profile).filter(Profile.email == email).first()
    user = db.query(User).filter(User.email == email).first()
    
    if not profile and not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Only User table has password (Profile uses Supabase auth)
    if user:
        user.hashed_password = get_password_hash(new_password)
        db.commit()
    
    reset_codes.pop(email)

    return {"message": "Password reset successfully"}
