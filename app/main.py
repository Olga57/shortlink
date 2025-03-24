from fastapi import FastAPI, Depends, HTTPException, status, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from sqlalchemy.orm import Session
from typing import List, Optional
import time
import threading

# Используем абсолютные пути для импортов
import models
import schemas
import crud
import auth
from database import engine, get_db
from redis_client import redis_client

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="URL Shortener API", description="API для сокращения ссылок")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключаем аутентификацию и авторизацию
app.include_router(auth.router, tags=["auth"])


# Периодическая очистка системы от просроченных ссылок
def delete_expired_links_task():
    while True:
        try:
            db = next(get_db())
            deleted_count = crud.delete_expired_links(db)
            print(f"Удалено {deleted_count} истекших ссылок")
        except Exception as e:
            print(f"Ошибка при удалении истекших ссылок: {e}")
        finally:
            # Интервал выполнения - 10 минут
            time.sleep(600)


# Инициализация фонового процесса
background_thread = threading.Thread(target=delete_expired_links_task, daemon=True)
background_thread.start()


@app.get("/")
def read_root():
    return {"message": "Добро пожаловать в API сервис сокращения ссылок"}


@app.post("/links/shorten", response_model=schemas.LinkResponse, tags=["links"])
def create_short_link(
    link: schemas.LinkCreate,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(auth.get_current_user_optional)
):
    """Генерация и регистрация сокращенной ссылки (доступно для всех пользователей)"""
    try:
        # Валидация пользовательского алиаса на уникальность
        if link.custom_alias:
            existing_link = crud.get_link_by_short_code(db, link.custom_alias)
            if existing_link:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Такой короткий код уже используется"
                )
        
        # Поиск дубликатов URL в системе
        if not link.custom_alias:
            existing_link = crud.get_link_by_original_url(db, link.original_url)
            if existing_link:
                return schemas.LinkResponse(
                    original_url=existing_link.original_url,
                    short_code=existing_link.short_code,
                    created_at=existing_link.created_at,
                    expires_at=existing_link.expires_at,
                    project_id=existing_link.project_id
                )
        
        # Проверка прав доступа к коллекции
        if link.project_id is not None:
            if not current_user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Для использования проектов необходима авторизация"
                )
                
            project = crud.get_project(db, link.project_id)
            if not project or project.user_id != current_user.id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Проект не найден или не принадлежит вам"
                )
        
        # Регистрация нового сокращения
        user_id = current_user.id if current_user else None
        db_link = crud.create_link(db, link, user_id)
        
        return schemas.LinkResponse(
            original_url=db_link.original_url,
            short_code=db_link.short_code,
            created_at=db_link.created_at,
            expires_at=db_link.expires_at,
            project_id=db_link.project_id
        )
    except Exception as e:
        # Журналирование инцидента
        print(f"Ошибка при создании ссылки: {str(e)}")
        # Формирование информативного ответа клиенту
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Произошла ошибка при создании ссылки: {str(e)}"
        )


@app.get("/{short_code}", tags=["links"])
def redirect_to_original_url(short_code: str, db: Session = Depends(get_db)):
    """Переадресация пользователя по короткому идентификатору (публичный доступ)"""
    # Приоритетная проверка в кэше для быстродействия
    cached_url = redis_client.get(f"link:{short_code}")
    
    if cached_url:
        # Инкремент счетчика и обновление метки последнего использования
        crud.increment_link_clicks(db, short_code)
        # Инвалидация кэша метрик
        redis_client.delete(f"stats:{short_code}")
        return RedirectResponse(url=cached_url.decode("utf-8"))
    
    # Поиск в основном хранилище при отсутствии в кэше
    link = crud.get_link_by_short_code(db, short_code)
    if not link:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Короткая ссылка не найдена"
        )
    
    # Контроль срока жизни ссылки
    if crud.is_link_expired(link):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Срок действия ссылки истек"
        )
    
    # Инкремент счетчика и обновление метки последнего использования
    crud.increment_link_clicks(db, short_code)
    # Инвалидация кэша метрик
    redis_client.delete(f"stats:{short_code}")
    
    # Сохранение URL в быстрое хранилище
    redis_client.set(f"link:{short_code}", link.original_url, ex=3600)  # Срок хранения 1 час
    
    return RedirectResponse(url=link.original_url)


@app.delete("/links/{short_code}", status_code=status.HTTP_204_NO_CONTENT, tags=["links"])
def delete_link(
    short_code: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """Деактивация и удаление короткой ссылки (только для авторизованных пользователей)"""
    link = crud.get_link_by_short_code(db, short_code)
    if not link:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Короткая ссылка не найдена"
        )
    
    # Контроль прав доступа к операции удаления
    if link.user_id is not None and link.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="У вас нет прав на удаление этой ссылки"
        )
    
    crud.delete_link(db, short_code)
    
    # Очистка всех связанных элементов кэша
    redis_client.delete(f"link:{short_code}")
    redis_client.delete(f"stats:{short_code}")
    
    return {"detail": "Ссылка успешно удалена"}


@app.put("/links/{short_code}", response_model=schemas.LinkResponse, tags=["links"])
def update_link(
    short_code: str,
    link_update: schemas.LinkUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """Модификация параметров существующей ссылки (требуется авторизация)"""
    link = crud.get_link_by_short_code(db, short_code)
    if not link:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Короткая ссылка не найдена"
        )
    
    # Проверяем, принадлежит ли ссылка текущему пользователю
    if link.user_id is not None and link.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="У вас нет прав на изменение этой ссылки"
        )
    
    # Если указан project_id, проверяем, существует ли проект и принадлежит ли он пользователю
    if link_update.project_id is not None:
        project = crud.get_project(db, link_update.project_id)
        if not project or project.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Проект не найден или не принадлежит вам"
            )
    
    updated_link = crud.update_link(db, short_code, link_update)
    
    # Очищаем кэш
    redis_client.delete(f"link:{short_code}")
    redis_client.delete(f"stats:{short_code}")
    
    return schemas.LinkResponse(
        original_url=updated_link.original_url,
        short_code=updated_link.short_code,
        created_at=updated_link.created_at,
        expires_at=updated_link.expires_at,
        project_id=updated_link.project_id
    )


@app.get("/links/{short_code}/stats", response_model=schemas.LinkStats, tags=["links"])
def get_link_stats(short_code: str, db: Session = Depends(get_db)):
    """Получение статистики по короткой ссылке (доступно для всех пользователей)"""
    # Проверяем кэш
    cached_stats = redis_client.get(f"stats:{short_code}")
    if cached_stats:
        import json
        stats_dict = json.loads(cached_stats.decode("utf-8"))
        return schemas.LinkStats(**stats_dict)
    
    link = crud.get_link_by_short_code(db, short_code)
    if not link:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Короткая ссылка не найдена"
        )
    
    stats = schemas.LinkStats(
        original_url=link.original_url,
        created_at=link.created_at,
        clicks=link.clicks,
        last_used_at=link.last_used_at,
        project_id=link.project_id
    )
    
    # Кэшируем статистику на более короткое время
    redis_client.set(
        f"stats:{short_code}",
        stats.json(),
        ex=60  # Кэш на 1 минуту вместо 5 минут
    )
    
    return stats


@app.get("/links/search", response_model=List[schemas.LinkResponse], tags=["links"])
def search_links_by_original_url(
    original_url: str,
    db: Session = Depends(get_db)
):
    """Поиск ссылок по оригинальному URL (доступно для всех пользователей)"""
    links = crud.search_links_by_original_url(db, original_url)
    return [
        schemas.LinkResponse(
            original_url=link.original_url,
            short_code=link.short_code,
            created_at=link.created_at,
            expires_at=link.expires_at,
            project_id=link.project_id
        ) for link in links
    ]


@app.delete("/links/cleanup", response_model=dict, tags=["links"])
def cleanup_unused_links(
    days: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """Удаление неиспользуемых ссылок (только для авторизованных пользователей)"""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Необходимы права администратора"
        )
    
    count = crud.delete_unused_links(db, days)
    return {"detail": f"Удалено {count} неиспользуемых ссылок"}


@app.get("/links/expired", response_model=List[schemas.LinkExpiredResponse], tags=["links"])
def get_expired_links(
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(auth.get_current_user_optional)
):
    """Получение истекших ссылок (для авторизованных - свои, для неавторизованных - анонимные)"""
    user_id = current_user.id if current_user else None
    links = crud.get_expired_links(db, user_id)
    return [
        schemas.LinkExpiredResponse(
            original_url=link.original_url,
            short_code=link.short_code,
            created_at=link.created_at,
            expires_at=link.expires_at,
            clicks=link.clicks,
            last_used_at=link.last_used_at,
            project_id=link.project_id
        ) for link in links
    ]


# --- Новые маршруты для работы с проектами ---

@app.post("/projects/", response_model=schemas.Project, tags=["projects"])
def create_project(
    project: schemas.ProjectCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """Создание нового проекта для группировки ссылок (только для авторизованных пользователей)"""
    return crud.create_project(db, project, current_user.id)


@app.get("/projects/", response_model=List[schemas.Project], tags=["projects"])
def get_user_projects(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """Получение списка проектов пользователя (только для авторизованных пользователей)"""
    return crud.get_user_projects(db, current_user.id)


@app.get("/projects/{project_id}", response_model=schemas.ProjectWithLinks, tags=["projects"])
def get_project_with_links(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """Получение детальной информации о коллекции включая связанные ссылки (авторизованный доступ)"""
    project = crud.get_project(db, project_id)
    if not project or project.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Проект не найден или не принадлежит вам"
        )
    
    links = crud.get_project_links(db, project_id)
    links_dicts = [
        {
            "original_url": link.original_url,
            "short_code": link.short_code,
            "created_at": link.created_at,
            "expires_at": link.expires_at,
            "project_id": link.project_id
        } for link in links
    ]
    
    return schemas.ProjectWithLinks(
        id=project.id,
        name=project.name,
        description=project.description,
        created_at=project.created_at,
        user_id=project.user_id,
        links=links_dicts
    )


@app.put("/projects/{project_id}", response_model=schemas.Project, tags=["projects"])
def update_project(
    project_id: int,
    project: schemas.ProjectUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """Обновление названия и описания существующей коллекции (доступно владельцу)"""
    db_project = crud.get_project(db, project_id)
    if not db_project or db_project.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Проект не найден или не принадлежит вам"
        )
    
    return crud.update_project(db, project_id, project)


@app.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["projects"])
def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """Удаление проекта (только для авторизованных пользователей)"""
    db_project = crud.get_project(db, project_id)
    if not db_project or db_project.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Проект не найден или не принадлежит вам"
        )
    
    crud.delete_project(db, project_id)
    return {"detail": "Проект успешно удален"}


@app.post("/links/{link_id}/add-to-project/{project_id}", status_code=status.HTTP_200_OK, tags=["projects"])
def add_link_to_project(
    link_id: int,
    project_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """Добавление ссылки в проект (только для авторизованных пользователей)"""
    link = db.query(models.Link).filter(models.Link.id == link_id).first()
    if not link or (link.user_id and link.user_id != current_user.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ссылка не найдена или не принадлежит вам"
        )
    
    project = crud.get_project(db, project_id)
    if not project or project.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Проект не найден или не принадлежит вам"
        )
    
    crud.add_link_to_project(db, link_id, project_id)
    
    # Очищаем кэш
    redis_client.delete(f"stats:{link.short_code}")
    
    return {"detail": "Ссылка добавлена в проект"}


@app.post("/links/{link_id}/remove-from-project", status_code=status.HTTP_200_OK, tags=["projects"])
def remove_link_from_project(
    link_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """Удаление ссылки из проекта (только для авторизованных пользователей)"""
    link = db.query(models.Link).filter(models.Link.id == link_id).first()
    if not link or (link.user_id and link.user_id != current_user.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ссылка не найдена или не принадлежит вам"
        )
    
    crud.remove_link_from_project(db, link_id)
    
    # Очищаем кэш
    redis_client.delete(f"stats:{link.short_code}")
    
    return {"detail": "Ссылка удалена из проекта"} 