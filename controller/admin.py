from fastapi import APIRouter, Depends, HTTPException, Body
from fastapi.responses import FileResponse
from database.models import AdminLogin, Question, UserAnswer, User, Company, Section, Profile
from sqlalchemy.orm import Session
from sqlalchemy import text
from passlib.context import CryptContext
from .basemodel import QuestionCreate, QuestionUpdate, SectionCreate, SectionUpdate, AdminLoginRequest
from database.database import get_db
from dotenv import load_dotenv
from openai import OpenAI
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from datetime import datetime
import tempfile
import re
from statistics import mean, stdev

router = APIRouter()
load_dotenv()

openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
ADMIN_EMAIL = "stefan.zanetti@pivotal.ag"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def create_default_admin():
    from database.database import SessionLocal
    from sqlalchemy import func
    db = SessionLocal()
    try:
        email = ADMIN_EMAIL.lower().strip()
        password = "admin123"
        
        # Check if admin with the correct email exists (case-insensitive)
        existing = db.query(AdminLogin).filter(
            func.lower(AdminLogin.email) == email
        ).first()
        
        if existing:
            # Update email to match exactly (case-sensitive match)
            if existing.email != ADMIN_EMAIL:
                existing.email = ADMIN_EMAIL
            # Verify password is correct (update if needed)
            if not verify_password(password, existing.hashed_password):
                # Password doesn't match, update it
                existing.hashed_password = get_password_hash(password)
            db.commit()
        else:
            # Admin doesn't exist, create it
            hashed = get_password_hash(password)
            admin = AdminLogin(email=ADMIN_EMAIL, hashed_password=hashed)
            db.add(admin)
            db.commit()
    except Exception as e:
        print(f"Error creating/updating default admin: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()

@router.post("/login/")
def login(login_request: AdminLoginRequest, db: Session = Depends(get_db)):
    try:
        # Trim email to handle whitespace
        email = login_request.email.strip().lower() if login_request.email else ""
        password = login_request.password
        
        if not email:
            raise HTTPException(status_code=400, detail="Email is required")
        if not password:
            raise HTTPException(status_code=400, detail="Password is required")
        
        user = db.query(AdminLogin).filter(AdminLogin.email == email).first()
        if not user:
            raise HTTPException(status_code=401, detail="Invalid email or password")
        
        if not verify_password(password, user.hashed_password):
            raise HTTPException(status_code=401, detail="Invalid email or password")
        
        return {"message": "Login successful", "email": user.email}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"Error in admin login: {str(e)}")
        print(f"Traceback: {error_trace}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.post("/create-question/")
def create_question(question: QuestionCreate, db: Session = Depends(get_db)):
    # Handle field name aliases (positive_rating_text -> rating_3_text)
    rating_3 = question.rating_3_text or question.positive_rating_text
    rating_neg3 = question.rating_neg3_text or question.negative_rating_text
    
    # Safely get show_rating_scale, defaulting to True if not provided or column doesn't exist
    show_rating = True
    if hasattr(question, 'show_rating_scale'):
        show_rating = question.show_rating_scale if question.show_rating_scale is not None else True
    
    db_question = Question(
        subject=question.subject,
        question=question.question,
        section_id=question.section_id,
        rating_3_text=rating_3,
        rating_neg3_text=rating_neg3,
        show_rating_scale=show_rating
        # created_at is automatically set by the database default
    )
    db.add(db_question)
    db.commit()
    db.refresh(db_question)
    return {"message": "Question created successfully!", "question_id": db_question.id}

def generate_feedback(prompt: str) -> str:
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a helpful assistant to analyze the question and generate feedback."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=150
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating feedback: {str(e)}")

def send_feedback_email_to_admin_with_attachment(txt_path: str):
    smtp_email = os.getenv("SMTP_EMAIL")
    smtp_password = os.getenv("SMTP_PASSWORD")
    
    if not smtp_email or not smtp_password:
        raise HTTPException(status_code=500, detail="SMTP credentials not configured")
    
    msg = MIMEMultipart()
    msg["Subject"] = "AI-Generated Collective Feedback Report"
    msg["From"] = smtp_email
    msg["To"] = ADMIN_EMAIL

    body = "<html><body><p>Attached is the AI-generated collective feedback report based on all user responses.</p></body></html>"
    msg.attach(MIMEText(body, "html"))

    with open(txt_path, "rb") as file:
        part = MIMEApplication(file.read(), Name=os.path.basename(txt_path))
        part["Content-Disposition"] = f'attachment; filename="{os.path.basename(txt_path)}"'
        msg.attach(part)

    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(smtp_email, smtp_password)
            server.send_message(msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send email with attachment: {str(e)}")

def sanitize_text(text: str, max_length=1000, chunk_size=40) -> str:
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text)
    broken_text = []
    for word in text.split():
        if len(word) > chunk_size:
            broken_text.extend([word[i:i+chunk_size] + ' ' for i in range(0, len(word), chunk_size)])
        else:
            broken_text.append(word)
    return ' '.join(broken_text)[:max_length]

@router.get("/get-all-questions/")
def get_all_questions(db: Session = Depends(get_db)):
    """Get all questions grouped by sections"""
    try:
        sections = db.query(Section).order_by(Section.label).all()
        
        if not sections:
            return []
        
        result = []
        for section in sections:
            questions = db.query(Question).filter(Question.section_id == section.id).all()
            section_data = {
                "section_id": section.id,
                "label": section.label or "",
                "title": section.title or "",
                "company_id": section.company_id,
                "questions": []
            }
            
            for question in questions:
                try:
                    answers = db.query(UserAnswer).filter(UserAnswer.question_id == question.id).all()
                    question_data = {
                        "question_id": question.id,
                        "subject": getattr(question, 'subject', None),  # Handle if subject column doesn't exist
                        "question": question.question or "",
                        "section_id": question.section_id,
                        "rating_3_text": question.rating_3_text,
                        "rating_neg3_text": question.rating_neg3_text,
                        "show_rating_scale": getattr(question, 'show_rating_scale', True),  # Default to True for backward compatibility
                        "created_at": None
                    }
                    
                    # Safely handle datetime serialization
                    if question.created_at:
                        try:
                            question_data["created_at"] = question.created_at.isoformat()
                        except (AttributeError, TypeError):
                            question_data["created_at"] = str(question.created_at) if question.created_at else None
                    
                    question_data["answers"] = []
                    for a in answers:
                        answer_data = {
                            "answer_id": a.id,
                            "answer": a.answer,
                            "feedback": a.feedback,
                            "rating": a.rating,
                            "user_id": a.user_id,
                            "email": None,
                            "submitted_at": None
                        }
                        
                        # Get user email safely - check Profile first (uuid), then User (int)
                        try:
                            # Try Profile first (uuid)
                            profile = db.query(Profile).filter(Profile.id == a.user_id).first()
                            if profile:
                                answer_data["email"] = profile.email
                            else:
                                # Fallback to User (int) - though this shouldn't happen with new schema
                                user_email = db.query(User.email).filter(User.id == a.user_id).scalar()
                                if user_email:
                                    answer_data["email"] = user_email
                        except Exception:
                            pass
                        
                        # Safely handle datetime serialization
                        if a.submitted_at:
                            try:
                                answer_data["submitted_at"] = a.submitted_at.isoformat()
                            except (AttributeError, TypeError):
                                answer_data["submitted_at"] = str(a.submitted_at) if a.submitted_at else None
                        
                        question_data["answers"].append(answer_data)
                    
                    section_data["questions"].append(question_data)
                except Exception as e:
                    print(f"Error processing question {question.id}: {str(e)}")
                    continue
            
            result.append(section_data)
        
        return result
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"Error in get_all_questions: {str(e)}")
        print(f"Traceback: {error_trace}")
        raise HTTPException(status_code=500, detail=f"Error fetching questions: {str(e)}")

@router.get("/get-questions-by-company/{company_id}")
def get_questions_by_company(company_id: int, db: Session = Depends(get_db)):
    """Get all questions grouped by sections for a specific company"""
    try:
        # Validate company exists
        company = db.query(Company).filter(Company.id == company_id).first()
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")
        
        # Get sections for this company
        sections = db.query(Section).filter(Section.company_id == company_id).order_by(Section.label).all()
        
        if not sections:
            return []
        
        result = []
        for section in sections:
            questions = db.query(Question).filter(Question.section_id == section.id).all()
            section_data = {
                "section_id": section.id,
                "label": section.label or "",
                "title": section.title or "",
                "company_id": section.company_id,
                "questions": []
            }
            
            for question in questions:
                try:
                    answers = db.query(UserAnswer).filter(UserAnswer.question_id == question.id).all()
                    
                    # Calculate average rating and standard deviation for CSV export
                    ratings = [a.rating for a in answers if a.rating is not None]
                    avg_rating = round(mean(ratings), 2) if ratings else None
                    std_dev = round(stdev(ratings), 2) if len(ratings) > 1 else None
                    
                    question_data = {
                        "question_id": question.id,
                        "subject": getattr(question, 'subject', None),  # Handle if subject column doesn't exist
                        "question": question.question or "",
                        "section_id": question.section_id,
                        "rating_3_text": question.rating_3_text,
                        "rating_neg3_text": question.rating_neg3_text,
                        "show_rating_scale": getattr(question, 'show_rating_scale', True),  # Default to True for backward compatibility
                        "avg_rating": avg_rating,
                        "std_dev": std_dev,
                        "created_at": None
                    }
                    
                    # Safely handle datetime serialization
                    if question.created_at:
                        try:
                            question_data["created_at"] = question.created_at.isoformat()
                        except (AttributeError, TypeError):
                            question_data["created_at"] = str(question.created_at) if question.created_at else None
                    
                    question_data["answers"] = []
                    for a in answers:
                        answer_data = {
                            "answer_id": a.id,
                            "answer": a.answer,
                            "feedback": a.feedback,
                            "rating": a.rating,
                            "user_id": a.user_id,
                            "email": None,
                            "user_email": None,  # Also include as user_email for frontend compatibility
                            "user_name": None,
                            "submitted_at": None
                        }
                        
                        # Get user email and name safely - check Profile first (uuid), then User (int)
                        try:
                            # Try Profile first (uuid)
                            profile = db.query(Profile).filter(Profile.id == a.user_id).first()
                            if profile:
                                answer_data["email"] = profile.email
                                answer_data["user_email"] = profile.email
                                answer_data["user_name"] = profile.name
                            else:
                                # Fallback to User (int) - though this shouldn't happen with new schema
                                user = db.query(User).filter(User.id == a.user_id).first()
                                if user:
                                    answer_data["email"] = user.email
                                    answer_data["user_email"] = user.email
                                    answer_data["user_name"] = user.name
                        except Exception:
                            pass
                        
                        # Safely handle datetime serialization
                        if a.submitted_at:
                            try:
                                answer_data["submitted_at"] = a.submitted_at.isoformat()
                            except (AttributeError, TypeError):
                                answer_data["submitted_at"] = str(a.submitted_at) if a.submitted_at else None
                        
                        question_data["answers"].append(answer_data)
                    
                    section_data["questions"].append(question_data)
                except Exception as e:
                    print(f"Error processing question {question.id}: {str(e)}")
                    continue
            
            result.append(section_data)
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"Error in get_questions_by_company: {str(e)}")
        print(f"Traceback: {error_trace}")
        raise HTTPException(status_code=500, detail=f"Error fetching questions: {str(e)}")

@router.get("/generate-feedback/{answer_id}")
def generate_feedback_for_answer(answer_id: int, db: Session = Depends(get_db)):
    db_answer = db.query(UserAnswer).filter(UserAnswer.id == answer_id).first()
    if not db_answer:
        raise HTTPException(status_code=404, detail="Answer not found")
    prompt = f"You are a helpful assistant. Provide feedback on the following answer:\nAnswer: {db_answer.answer}"
    feedback = generate_feedback(prompt)
    db_answer.feedback = feedback
    db_answer.feedback_generated = True
    db.commit()
    db.refresh(db_answer)
    return {"message": "Feedback generated", "feedback": feedback, "answer_id": db_answer.id}

@router.get("/generate-collective-report")
def generate_collective_feedback_report(db: Session = Depends(get_db)):
    questions = db.query(Question).all()
    if not questions:
        raise HTTPException(status_code=404, detail="No questions found")

    report = []
    for idx, q in enumerate(questions, 1):
        answers = db.query(UserAnswer).filter(UserAnswer.question_id == q.id).all()

        if not answers:
            continue

        ratings = [a.rating for a in answers if a.rating is not None]
        avg_rating = round(mean(ratings), 2) if ratings else "N/A"
        rating_label = "Good" if isinstance(avg_rating, (int, float)) and avg_rating > 0 else ("Neutral" if avg_rating == 0 else "Poor")

        all_user_answers = "\n".join([f"- {a.answer}" for a in answers if a.answer])
        prompt = f"""You are an evaluator analyzing user answers.
Q{idx}: {q.question}
Average Rating: {avg_rating} ({rating_label})
User Answers:\n{all_user_answers}

Generate an AI summary that captures sentiment, strengths, and common misunderstandings based on these user answers.
"""
        ai_summary = generate_feedback(prompt)
        report.append({
            "question": f"Q{idx}: {q.question}",
            "avg_rating": avg_rating,
            "rating_label": rating_label,
            "summary": ai_summary
        })

    if not report:
        return {"message": "No data available for collective report."}

    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w", encoding="utf-8") as tmp:
        for r in report:
            tmp.write(f"{r['question']}\n")
            tmp.write(f"Rating: {r['avg_rating']} ({r['rating_label']})\n")
            tmp.write(f"Summary: {r['summary']}\n")
            tmp.write("---\n")
        file_path = tmp.name

    send_feedback_email_to_admin_with_attachment(file_path)

    return FileResponse(path=file_path, filename="collective_feedback_report.txt", media_type="text/plain")

# Section Management Endpoints
@router.post("/create-section/")
def create_section(section: SectionCreate, db: Session = Depends(get_db)):
    """Create a new section"""
    # Validate company_id if provided
    if section.company_id is not None:
        company = db.query(Company).filter(Company.id == section.company_id).first()
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")
    
    new_section = Section(
        label=section.label,
        title=section.title,
        company_id=section.company_id
    )
    db.add(new_section)
    db.commit()
    db.refresh(new_section)
    return {"message": "Section created successfully", "section_id": new_section.id}

@router.put("/update-section-title/{section_id}")
def update_section_title(section_id: int, section_update: SectionUpdate, db: Session = Depends(get_db)):
    """Update section title (and optionally label and company_id)"""
    section = db.query(Section).filter(Section.id == section_id).first()
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    
    if section_update.title is not None:
        section.title = section_update.title
    if section_update.label is not None:
        section.label = section_update.label
    if section_update.company_id is not None:
        # Validate company exists
        company = db.query(Company).filter(Company.id == section_update.company_id).first()
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")
        section.company_id = section_update.company_id
    
    db.commit()
    db.refresh(section)
    return {"message": "Section updated successfully", "section": {"id": section.id, "label": section.label, "title": section.title}}

@router.delete("/delete-section/{section_id}")
def delete_section(section_id: int, db: Session = Depends(get_db)):
    """Delete a section and set question section_id to NULL"""
    section = db.query(Section).filter(Section.id == section_id).first()
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    
    # Set section_id to NULL for all questions in this section
    questions_updated = db.query(Question).filter(Question.section_id == section_id).update(
        {Question.section_id: None},
        synchronize_session=False
    )
    
    db.delete(section)
    db.commit()
    
    message = f"Section deleted successfully"
    if questions_updated > 0:
        message += f". {questions_updated} question(s) had their section_id set to NULL."
    
    return {"message": message}

# Question Management Endpoints
@router.put("/update-question/{question_id}")
def update_question(question_id: int, question_update: QuestionUpdate, db: Session = Depends(get_db)):
    """Update a question"""
    question = db.query(Question).filter(Question.id == question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    
    if question_update.question is not None:
        question.question = question_update.question
    if question_update.section_id is not None:
        # Validate section exists
        section = db.query(Section).filter(Section.id == question_update.section_id).first()
        if not section:
            raise HTTPException(status_code=404, detail="Section not found")
        question.section_id = question_update.section_id
    
    # Handle field name aliases
    rating_3 = question_update.rating_3_text or question_update.positive_rating_text
    rating_neg3 = question_update.rating_neg3_text or question_update.negative_rating_text
    
    if rating_3 is not None:
        question.rating_3_text = rating_3
    if rating_neg3 is not None:
        question.rating_neg3_text = rating_neg3
    
    if question_update.show_rating_scale is not None:
        # Only update if column exists in database
        if hasattr(question, 'show_rating_scale'):
            question.show_rating_scale = question_update.show_rating_scale
    
    db.commit()
    db.refresh(question)
    return {"message": "Question updated successfully", "question_id": question.id}

@router.delete("/delete-question/{question_id}")
def delete_question(question_id: int, db: Session = Depends(get_db)):
    """Delete a question"""
    question = db.query(Question).filter(Question.id == question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    
    # Delete all answers for this question
    answers_deleted = db.query(UserAnswer).filter(UserAnswer.question_id == question_id).delete()
    
    db.delete(question)
    db.commit()
    
    message = f"Question deleted successfully"
    if answers_deleted > 0:
        message += f". {answers_deleted} answer(s) were also deleted."
    
    return {"message": message}

# Company Management Endpoints
@router.get("/get-companies")
def get_companies(db: Session = Depends(get_db)):
    companies = db.query(Company).all()
    return [{"id": company.id, "name": company.name} for company in companies]

@router.post("/add-company")
def add_company(company_name: str = Body(...), db: Session = Depends(get_db)):
    # Check if company already exists
    existing = db.query(Company).filter(Company.name == company_name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Company already exists")
    
    new_company = Company(name=company_name)
    db.add(new_company)
    db.commit()
    db.refresh(new_company)
    return {"message": "Company added successfully", "company": {"id": new_company.id, "name": new_company.name}}

@router.put("/update-company/{company_id}")
def update_company(company_id: int, company_name: str = Body(...), db: Session = Depends(get_db)):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    
    # Check if name already exists (excluding current company)
    existing = db.query(Company).filter(Company.name == company_name, Company.id != company_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Company name already exists")
    
    company.name = company_name
    db.commit()
    db.refresh(company)
    return {"message": "Company updated successfully", "company": {"id": company.id, "name": company.name}}

@router.get("/check-company-deletion/{company_id}")
def check_company_deletion(company_id: int, db: Session = Depends(get_db)):
    """Diagnostic endpoint to check what's preventing company deletion"""
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    
    users_count = db.query(User).filter(User.company_id == company_id).count()
    sections_count = db.query(Section).filter(Section.company_id == company_id).count()
    
    # Check for questions via sections
    sections = db.query(Section).filter(Section.company_id == company_id).all()
    section_ids = [s.id for s in sections]
    questions_count = 0
    if section_ids:
        questions_count = db.query(Question).filter(Question.section_id.in_(section_ids)).count()
    
    return {
        "company_id": company_id,
        "company_name": company.name,
        "users_count": users_count,
        "sections_count": sections_count,
        "questions_via_sections_count": questions_count,
        "can_delete": users_count == 0 and sections_count == 0
    }

@router.delete("/delete-company/{company_id}")
def delete_company(company_id: int, db: Session = Depends(get_db)):
    try:
        company = db.query(Company).filter(Company.id == company_id).first()
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")
        
        # Get counts before deletion for informational purposes
        users_count = db.query(User).filter(User.company_id == company_id).count()
        sections_count = db.query(Section).filter(Section.company_id == company_id).count()
        
        # Manually set company_id to NULL for all related users
        # Use raw SQL as fallback if ORM update fails (handles database-level constraints better)
        users_updated = 0
        try:
            # Try ORM update first
            users_updated = db.query(User).filter(User.company_id == company_id).update(
                {User.company_id: None},
                synchronize_session=False
            )
            db.commit()
            if users_updated > 0:
                print(f"Updated {users_updated} user(s) to remove company_id")
        except Exception as e:
            db.rollback()
            error_msg = str(e)
            print(f"ORM update failed for users: {error_msg}")
            # Try raw SQL as fallback
            try:
                result = db.execute(text("UPDATE users SET company_id = NULL WHERE company_id = :company_id"), 
                                   {"company_id": company_id})
                users_updated = result.rowcount
                db.commit()
                if users_updated > 0:
                    print(f"Updated {users_updated} user(s) using raw SQL")
            except Exception as sql_error:
                db.rollback()
                print(f"Raw SQL update also failed for users: {str(sql_error)}")
                users_updated = 0
        
        # Manually set company_id to NULL for all related sections
        sections_updated = 0
        try:
            # Try ORM update first
            sections_updated = db.query(Section).filter(Section.company_id == company_id).update(
                {Section.company_id: None},
                synchronize_session=False
            )
            db.commit()
            if sections_updated > 0:
                print(f"Updated {sections_updated} section(s) to remove company_id")
        except Exception as e:
            db.rollback()
            error_msg = str(e)
            print(f"ORM update failed for sections: {error_msg}")
            # Try raw SQL as fallback
            try:
                result = db.execute(text("UPDATE sections SET company_id = NULL WHERE company_id = :company_id"), 
                                   {"company_id": company_id})
                sections_updated = result.rowcount
                db.commit()
                if sections_updated > 0:
                    print(f"Updated {sections_updated} section(s) using raw SQL")
            except Exception as sql_error:
                db.rollback()
                print(f"Raw SQL update also failed for sections: {str(sql_error)}")
                sections_updated = 0
        
        # Refresh the company object to ensure we have the latest state
        db.refresh(company)
        
        # Now try to delete the company
        try:
            db.delete(company)
            db.commit()
            print(f"Successfully deleted company {company_id}")
        except Exception as delete_error:
            db.rollback()
            error_msg = str(delete_error)
            print(f"Error deleting company after updates: {error_msg}")
            
            # Check if there are still references preventing deletion
            remaining_users = db.query(User).filter(User.company_id == company_id).count()
            remaining_sections = db.query(Section).filter(Section.company_id == company_id).count()
            
            if remaining_users > 0 or remaining_sections > 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot delete company. Still has {remaining_users} user(s) and {remaining_sections} section(s) associated. Database constraints may be preventing deletion."
                )
            
            # Check if it's a foreign key constraint error
            if "foreign key" in error_msg.lower() or "violates foreign key" in error_msg.lower() or "constraint" in error_msg.lower():
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot delete company due to database constraint: {error_msg}. You may need to configure foreign key constraints with ON DELETE SET NULL in your database."
                )
            raise HTTPException(status_code=500, detail=f"Error deleting company: {error_msg}")
        
        # Return success message with info about affected records
        message = "Company deleted successfully"
        if users_updated > 0 or sections_updated > 0:
            message += f" {users_updated} user(s) and {sections_updated} section(s) had their company_id set to NULL."
        
        return {"message": message}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        import traceback
        error_msg = str(e)
        error_trace = traceback.format_exc()
        
        # Log the full error for debugging
        print(f"Unexpected error deleting company: {error_msg}")
        print(f"Traceback: {error_trace}")
        
        raise HTTPException(status_code=500, detail=f"Error deleting company: {error_msg}")

# User Management Endpoints
@router.get("/get-users-by-company/{company_id}")
def get_users_by_company(company_id: int, db: Session = Depends(get_db)):
    """Get all users for a company with their answer completion status"""
    try:
        # Validate company exists
        company = db.query(Company).filter(Company.id == company_id).first()
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")
        
        # Get all profiles for this company
        profiles = db.query(Profile).filter(Profile.company_id == company_id).all()
        
        # Get all questions for this company (via sections)
        # Include both company-specific sections and global sections (company_id = null)
        from sqlalchemy import or_
        sections = db.query(Section).filter(
            or_(
                Section.company_id == company_id,
                Section.company_id.is_(None)  # Global sections available to all companies
            )
        ).all()
        section_ids = [s.id for s in sections]
        questions = db.query(Question).filter(Question.section_id.in_(section_ids)).all() if section_ids else []
        total_questions = len(questions)
        
        result = []
        for profile in profiles:
            # Get all answers for this user
            user_answers = db.query(UserAnswer).filter(UserAnswer.user_id == profile.id).all()
            
            # Count how many questions this user has answered
            answered_question_ids = set([a.question_id for a in user_answers])
            answered_count = len([qid for qid in answered_question_ids if qid in [q.id for q in questions]])
            
            # Check if user has completely answered all questions
            # A question is completely answered if:
            # 1. User marked "can't answer" (rating=0 and answer is blank), OR
            # 2. User provided non-zero rating AND feedback text
            completely_answered = True
            if total_questions > 0:
                for question in questions:
                    answer = next((a for a in user_answers if a.question_id == question.id), None)
                    if not answer:
                        completely_answered = False
                        break
                    # Check if answer is complete
                    has_rating = answer.rating is not None
                    has_answer_text = answer.answer and answer.answer.strip() != ""
                    is_cant_answer = has_rating and answer.rating == 0 and (not answer.answer or answer.answer.strip() == "")
                    is_complete = is_cant_answer or (has_rating and answer.rating != 0 and has_answer_text)
                    if not is_complete:
                        completely_answered = False
                        break
            
            # Calculate completion percentage
            completion_percentage = 0
            if total_questions > 0:
                completion_percentage = round((answered_count / total_questions) * 100, 1)
            
            result.append({
                "user_id": str(profile.id),
                "email": profile.email,
                "name": profile.name,
                "company_id": profile.company_id,
                "total_questions": total_questions,
                "answered_count": answered_count,
                "completion_percentage": completion_percentage,
                "completely_answered": completely_answered and answered_count == total_questions,
                "created_at": profile.created_at.isoformat() if profile.created_at else None
            })
        
        return {
            "company_id": company_id,
            "company_name": company.name,
            "users": result
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"Error in get_users_by_company: {str(e)}")
        print(f"Traceback: {error_trace}")
        raise HTTPException(status_code=500, detail=f"Error fetching users: {str(e)}")

@router.delete("/delete-user/{user_id}")
def delete_user(user_id: str, db: Session = Depends(get_db)):
    """Delete a user (profile) and all their answers"""
    try:
        import uuid
        # Convert string to UUID
        try:
            user_uuid = uuid.UUID(user_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid user ID format")
        
        # Find the profile
        profile = db.query(Profile).filter(Profile.id == user_uuid).first()
        if not profile:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Delete all answers for this user
        answers_deleted = db.query(UserAnswer).filter(UserAnswer.user_id == user_uuid).delete()
        
        # Delete the profile
        db.delete(profile)
        db.commit()
        
        return {
            "message": f"User deleted successfully",
            "answers_deleted": answers_deleted
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        import traceback
        error_trace = traceback.format_exc()
        print(f"Error deleting user: {str(e)}")
        print(f"Traceback: {error_trace}")
        raise HTTPException(status_code=500, detail=f"Error deleting user: {str(e)}")
