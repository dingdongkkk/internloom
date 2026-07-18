"""Auth router. [OPUS] — full, this is the pattern for all other routers.

Every handler returns ok(...)/paginated(...); errors are raised as ApiError and
formatted centrally. Request bodies validated by Pydantic (bad input -> 422 in the
standard envelope, never a crash).
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, constr
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.envelope import ok
from app.core.deps import get_current_user, CurrentUser
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


class StudentRegisterIn(BaseModel):
    email: EmailStr
    password: constr(min_length=8)


class CompanyRegisterIn(BaseModel):
    email: EmailStr
    password: constr(min_length=8)
    company_name: constr(min_length=2, max_length=255)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class VerifyOtpIn(BaseModel):
    user_id: int
    code: constr(min_length=6, max_length=6)


class EmailChangeIn(BaseModel):
    new_email: EmailStr


class RefreshIn(BaseModel):
    refresh_token: str


@router.post("/register/student", status_code=201)
def register_student(body: StudentRegisterIn, db: Session = Depends(get_db)):
    return ok(auth_service.register_student(db, email=body.email, password=body.password))


@router.post("/register/company", status_code=201)
def register_company(body: CompanyRegisterIn, db: Session = Depends(get_db)):
    return ok(auth_service.register_company(
        db, email=body.email, password=body.password, company_name=body.company_name))


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    return ok(auth_service.login(db, email=body.email, password=body.password))


@router.post("/verify-otp")
def verify_otp(body: VerifyOtpIn, db: Session = Depends(get_db)):
    return ok(auth_service.verify_otp(db, user_id=body.user_id, code=body.code))


@router.post("/request-email-change")
def request_email_change(body: EmailChangeIn,
                         current: CurrentUser = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    return ok(auth_service.request_email_change(db, user_id=current.id, new_email=body.new_email))


@router.post("/refresh")
def refresh(body: RefreshIn, db: Session = Depends(get_db)):
    return ok(auth_service.refresh(db, refresh_token=body.refresh_token))
