import logging
import secrets

import httpx

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.user import User
from app.services.auth.microsoft_oauth import MICROSOFT_TOKEN_URL, build_authorization_url

from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/auth",
    tags=["auth"]
)

@router.get("/microsoft/login")
def microsoft_login():
    state = secrets.token_urlsafe(32)
    
    authorization_url = build_authorization_url(
        state=state
    )
    
    return RedirectResponse(
        authorization_url
    )
    
@router.get("/microsoft/callback")
async def microsoft_callback(code:str | None = Query(default=None)):
    if not code:
        raise HTTPException(
            status_code=400,
            detail=(
                "Missing authorization code."
                "start login from '/auth/microsoft/login'"
            )
        )
    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            MICROSOFT_TOKEN_URL,
            data={
                "client_id":settings.MICROSOFT_CLIENT_ID,
                "client_secret":settings.MICROSOFT_CLIENT_SECRET,
                "code":code,
                "redirect_uri":settings.MICROSOFT_REDIRECT_URI,
                "grant_type":"authorization_code"
            }
        )
        
        if token_response.status_code != 200:
            logger.error(
                "Failed to obtain microsoft token: %s",
                token_response.text
            )
            
            raise HTTPException(
                status_code=400,
                detail="Microsoft token exchange failed."
            )
        
        token_data = token_response.json()
        
        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token")
        
        async with httpx.AsyncClient() as client:
            profile_response = await client.get(
                "https://graph.microsoft.com/v1.0/me",
                headers={
                    "Authorization":(
                        f"Bearer {access_token}"
                    )
                }
            )
            
            if profile_response.status_code !=200:
                raise HTTPException(
                    status_code=400,
                    detail="Failed to fetch microsoft profile."
                )
            
            profile = profile_response.json()
            
            db: Session = SessionLocal()
            
            try:
                
                user_email = profile.get("mail") or profile.get("userPrincipalName")
                
                if not user_email:
                    raise HTTPException(
                        status_code=400,
                        detail="Microsoft account email not available"
                    )
                
                existing_user = (
                    db.query(User).filter(
                        User.email == user_email
                    )
                    .first()
                )
                
                if existing_user:
                    existing_user.access_token = access_token
                    existing_user.refresh_token = refresh_token
                    
                    user = existing_user
                else:
                    user = User(
                        email = user_email,
                        full_name = profile.get("displayName"),
                        microsoft_id = profile["id"],
                        access_token=access_token,
                        refresh_token=refresh_token
                    )
                    
                    db.add(user)
                
                db.commit()
                db.refresh(user)
                
                response_data = {
                    "message": "Microsoft login successful.",
                    "email": user.email,
                }
                
            except Exception:
                db.rollback()
                logger.exception("Failed to persist Microsoft user.")
                
                raise
            
            finally:
                db.close()
                
            return response_data