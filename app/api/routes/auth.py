from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import select
from ...db import models, session
from ...schemas import user as user_schema
from ...services import utils


router = APIRouter(
    tags=["authentication"]
)

@router.post("/login/")
async def login(user: user_schema.UserAuthenticate, request: Request, db: Session = Depends(session.get_db)):
    stmt = select(models.User).where(models.User.email == user.email)
    result = await db.execute(stmt)
    db_user = result.scalars().first()
    if db_user is None or not utils.compare_hash(user.password, db_user.password_hash):
        raise HTTPException(status_code=403, detail="Email or Password is Incorrect")
    request.session["user_name"] = db_user.email
    return {"message": "Success"}

@router.post("/logout/")
async def logout(request: Request):
    user = request.session.get("user_name")
    if not user:
        raise HTTPException(status_code=401, detail="There is no active session")
    request.session.clear()
    return {"message": "Session closed"}

@router.post("/signup/", response_model=user_schema.UserResponse)
async def create_user(
    item: user_schema.UserCreate, 
    request: Request, 
    db: Session = Depends(session.get_db)
):
    stmt = select(models.User).where(models.User.email == item.email)
    result = await db.execute(stmt)
    existing_user = result.scalars().first()

    if existing_user:
        raise HTTPException(status_code=400, detail="User already registered")

    hashed_pwd = utils.get_hash(item.password)
    db_item = models.User(
        email=item.email, 
        password_hash=hashed_pwd,
        first_semester=item.first_semester
    )
    
    db.add(db_item)
    await db.commit() 
    await db.refresh(db_item) 

    request.session["user_name"] = db_item.email
    
    return db_item

@router.get("/me/")
async def read_me(request: Request):
    user = request.session.get("user_name")
    if not user:
        raise HTTPException(status_code=401, detail="There is no active session")
    return {"active_user": user}

@router.get("/email/{user_email}", response_model=user_schema.UserResponse)
async def get_user(user_email: str, db: Session = Depends(session.get_db)):
    stmt = select(models.User).where(models.User.email == user_email)
    result = await db.execute(stmt)
    db_user = result.scalars().first()
    if db_user is None:
        raise HTTPException(status_code=403, detail="That User was not Found")
    return db_user