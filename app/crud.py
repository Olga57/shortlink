import random
import string
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from typing import List, Optional

import models
import schemas


def generate_short_code(length: int = 6) -> str:
    """Формирует рандомный код для короткой ссылки указанной длины"""
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))


def get_link_by_short_code(db: Session, short_code: str) -> Optional[models.Link]:
    """Извлекает запись ссылки по короткому идентификатору"""
    return db.query(models.Link).filter(models.Link.short_code == short_code).first()


def get_link_by_original_url(db: Session, original_url: str) -> Optional[models.Link]:
    """Находит запись ссылки по её оригинальному адресу"""
    # Конвертируем объект Pydantic в строку при необходимости
    if hasattr(original_url, '__str__'):
        original_url = str(original_url)
    return db.query(models.Link).filter(models.Link.original_url == original_url).first()


def create_link(db: Session, link: schemas.LinkCreate, user_id: Optional[int] = None) -> models.Link:
    """Регистрирует новую сокращенную ссылку в системе"""
    # Используем пользовательский алиас, если предоставлен
    if link.custom_alias:
        short_code = link.custom_alias
    else:
        # Создаём уникальный идентификатор
        while True:
            short_code = generate_short_code()
            if not get_link_by_short_code(db, short_code):
                break
    
    # Конвертируем URL в строковое представление
    original_url = str(link.original_url)
    
    db_link = models.Link(
        original_url=original_url,
        short_code=short_code,
        expires_at=link.expires_at,
        user_id=user_id,
        project_id=link.project_id
    )
    db.add(db_link)
    db.commit()
    db.refresh(db_link)
    return db_link


def update_link(db: Session, short_code: str, link_update: schemas.LinkUpdate) -> models.Link:
    """Модифицирует существующую запись ссылки"""
    db_link = get_link_by_short_code(db, short_code)
    if db_link:
        # Конвертируем URL в строковое представление
        original_url = str(link_update.original_url)
        db_link.original_url = original_url
        if link_update.expires_at:
            db_link.expires_at = link_update.expires_at
        if link_update.project_id is not None:
            db_link.project_id = link_update.project_id
        db.commit()
        db.refresh(db_link)
    return db_link


def delete_link(db: Session, short_code: str) -> bool:
    """Удаляет запись ссылки из базы данных по короткому коду"""
    db_link = get_link_by_short_code(db, short_code)
    if db_link:
        db.delete(db_link)
        db.commit()
        return True
    return False


def increment_link_clicks(db: Session, short_code: str) -> None:
    """Инкрементирует счётчик и обновляет timestamp последнего использования"""
    db_link = get_link_by_short_code(db, short_code)
    if db_link:
        # Применяем временную зону
        now = datetime.now(timezone.utc)
        db_link.clicks += 1
        db_link.last_used_at = now
        db.commit()
        # Синхронизация с БД
        db.refresh(db_link)


def is_link_expired(link: models.Link) -> bool:
    """Проверяет валидность ссылки по сроку действия"""
    if link.expires_at:
        # Используем UTC для корректного сравнения временных меток
        now = datetime.now(timezone.utc)
        return link.expires_at < now
    return False


def search_links_by_original_url(db: Session, original_url: str) -> List[models.Link]:
    """Реализует поиск ссылок с похожим оригинальным URL"""
    return db.query(models.Link).filter(models.Link.original_url.contains(original_url)).all()


def delete_unused_links(db: Session, days: int) -> int:
    """Очищает неактивные ссылки старше указанного периода"""
    # Работаем с UTC
    now = datetime.now(timezone.utc)
    cutoff_date = now - timedelta(days=days)
    
    # Выбираем ссылки без активности
    unused_links = db.query(models.Link).filter(
        or_(
            models.Link.last_used_at < cutoff_date,
            and_(
                models.Link.last_used_at.is_(None),
                models.Link.created_at < cutoff_date
            )
        )
    ).all()
    
    count = len(unused_links)
    
    # Выполняем очистку
    for link in unused_links:
        db.delete(link)
    
    db.commit()
    return count


def get_expired_links(db: Session, user_id: Optional[int] = None) -> List[models.Link]:
    """Выбирает просроченные ссылки пользователя или гостевые при отсутствии user_id"""
    # Точка отсчета - текущее время с UTC
    now = datetime.now(timezone.utc)
    
    query = db.query(models.Link).filter(models.Link.expires_at < now)
    
    if user_id is not None:
        query = query.filter(models.Link.user_id == user_id)
    else:
        query = query.filter(models.Link.user_id.is_(None))
    
    return query.all()


def delete_expired_links(db: Session) -> int:
    """Очищает все ссылки с истекшим сроком действия"""
    # Используем UTC для временных меток
    now = datetime.now(timezone.utc)
    expired_links = db.query(models.Link).filter(
        models.Link.expires_at < now
    ).all()
    
    count = len(expired_links)
    
    # Удаляем просроченные записи
    for link in expired_links:
        db.delete(link)
    
    db.commit()
    return count


# Операции с проектами

def create_project(db: Session, project: schemas.ProjectCreate, user_id: int) -> models.Project:
    """Создаёт новую коллекцию для группировки ссылок"""
    db_project = models.Project(
        name=project.name,
        description=project.description,
        user_id=user_id
    )
    db.add(db_project)
    db.commit()
    db.refresh(db_project)
    return db_project


def get_project(db: Session, project_id: int) -> Optional[models.Project]:
    """Получает данные коллекции по идентификатору"""
    return db.query(models.Project).filter(models.Project.id == project_id).first()


def get_user_projects(db: Session, user_id: int) -> List[models.Project]:
    """Извлекает список коллекций конкретного пользователя"""
    return db.query(models.Project).filter(models.Project.user_id == user_id).all()


def update_project(db: Session, project_id: int, project: schemas.ProjectUpdate) -> Optional[models.Project]:
    """Обновляет метаданные коллекции"""
    db_project = get_project(db, project_id)
    if db_project:
        db_project.name = project.name
        db_project.description = project.description
        db.commit()
        db.refresh(db_project)
        return db_project
    return None


def delete_project(db: Session, project_id: int) -> bool:
    """Удаляет коллекцию и обнуляет связи со ссылками"""
    db_project = get_project(db, project_id)
    if db_project:
        # Сперва отвязываем все ссылки
        for link in db_project.links:
            link.project_id = None
        
        # Теперь удаляем саму коллекцию
        db.delete(db_project)
        db.commit()
        return True
    return False


def get_project_links(db: Session, project_id: int) -> List[models.Link]:
    """Извлекает все ссылки, относящиеся к коллекции"""
    return db.query(models.Link).filter(models.Link.project_id == project_id).all()


def add_link_to_project(db: Session, link_id: int, project_id: int) -> bool:
    """Присоединяет существующую ссылку к коллекции"""
    link = db.query(models.Link).filter(models.Link.id == link_id).first()
    if link:
        link.project_id = project_id
        db.commit()
        return True
    return False


def remove_link_from_project(db: Session, link_id: int) -> bool:
    """Отсоединяет ссылку от коллекции (сбрасывает project_id)"""
    link = db.query(models.Link).filter(models.Link.id == link_id).first()
    if link and link.project_id:
        link.project_id = None
        db.commit()
        return True
    return False 