
from sqlalchemy import Column, Integer, BigInteger, String, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from database.database import Base
import uuid




class AdminLogin(Base):
    __tablename__ = 'admin_login'
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)

class Question(Base):
    __tablename__ = 'questions'
    
    id = Column(BigInteger, primary_key=True, index=True)
    section_id = Column(BigInteger, ForeignKey('sections.id'), nullable=True, index=True)
    question = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    rating_3_text = Column(String, nullable=True)
    rating_neg3_text = Column(String, nullable=True)
    show_rating_scale = Column(Boolean, default=True)  # Whether to show -3 to +3 rating slider
    subject = Column(String, nullable=True)  # Kept for backward compatibility, not in ERD 

class UserAnswer(Base):
    __tablename__ = 'user_answers'
    
    id = Column(BigInteger, primary_key=True, index=True)
    question_id = Column(BigInteger, ForeignKey('questions.id'), index=True)  
    user_id = Column(UUID(as_uuid=True), ForeignKey('profiles.id'), index=True)     
    answer = Column(String)
    rating = Column(Integer, nullable=True) 
    feedback = Column(String, nullable=True) 
    feedback_generated = Column(Boolean, default=False)
    submitted_at = Column(DateTime(timezone=True), nullable=True)


class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    name = Column(String)
    hashed_password = Column(String)
    company_id = Column(BigInteger, ForeignKey('companies.id', ondelete='SET NULL'), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Profile(Base):
    __tablename__ = 'profiles'
    
    id = Column(UUID(as_uuid=True), primary_key=True, index=True)  # References auth.users.id in Supabase
    email = Column(String, unique=True, index=True)
    name = Column(String)
    company_id = Column(BigInteger, ForeignKey('companies.id', ondelete='SET NULL'), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Company(Base):
    __tablename__ = 'companies'
    
    id = Column(BigInteger, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Section(Base):
    __tablename__ = 'sections'
    
    id = Column(BigInteger, primary_key=True, index=True)
    label = Column(String, nullable=True)
    title = Column(String, nullable=True)
    company_id = Column(BigInteger, ForeignKey('companies.id', ondelete='SET NULL'), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
