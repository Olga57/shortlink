from pydantic import BaseModel, HttpUrl, validator, Field
from typing import Optional, List, ForwardRef, Any, Dict
from datetime import datetime


# Модели пользовательских данных
class UserBase(BaseModel):
    username: str
    email: str


class UserCreate(UserBase):
    password: str


class UserLogin(BaseModel):
    username: str
    password: str


class User(UserBase):
    id: int
    is_active: bool
    is_admin: bool
    created_at: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None


# Основные модели для URL-адресов
class LinkBase(BaseModel):
    original_url: HttpUrl


class LinkCreate(LinkBase):
    custom_alias: Optional[str] = None
    expires_at: Optional[datetime] = None
    project_id: Optional[int] = None

    @validator('custom_alias')
    def validate_custom_alias(cls, v):
        if v is not None:
            if len(v) < 3:
                raise ValueError('Короткий код должен содержать минимум 3 символа')
            if len(v) > 20:
                raise ValueError('Короткий код должен содержать максимум 20 символов')
            if not v.isalnum():
                raise ValueError('Короткий код должен содержать только буквы и цифры')
        return v


class LinkUpdate(BaseModel):
    original_url: HttpUrl
    expires_at: Optional[datetime] = None
    project_id: Optional[int] = None


class LinkResponse(BaseModel):
    original_url: str
    short_code: str
    created_at: datetime
    expires_at: Optional[datetime] = None
    project_id: Optional[int] = None

    class Config:
        from_attributes = True


class LinkStats(BaseModel):
    original_url: str
    created_at: datetime
    clicks: int
    last_used_at: Optional[datetime] = None
    project_id: Optional[int] = None

    class Config:
        from_attributes = True


class LinkExpiredResponse(LinkResponse):
    clicks: int
    last_used_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# Модели для организации ссылок
class ProjectBase(BaseModel):
    name: str
    description: Optional[str] = None


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(ProjectBase):
    pass


class Project(ProjectBase):
    id: int
    created_at: datetime
    user_id: int

    class Config:
        from_attributes = True


class ProjectWithLinks(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    created_at: datetime
    user_id: int
    links: List[Dict[str, Any]] = []

    class Config:
        from_attributes = True
        
    @classmethod
    def from_orm(cls, obj):
        # Трансформируем связанные объекты в удобный JSON-формат
        result = super().from_orm(obj)
        if hasattr(obj, 'links'):
            result.links = [
                {
                    "original_url": link.original_url,
                    "short_code": link.short_code,
                    "created_at": link.created_at,
                    "expires_at": link.expires_at,
                    "project_id": link.project_id
                }
                for link in obj.links
            ]
        return result 