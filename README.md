# URL Shortener API

Сервис для сокращения URL-адресов с поддержкой статистики, проектов и пользовательских функций.

## Возможности

### Основные функции:

1. **Управление ссылками**:
   - `POST /links/shorten` – создание короткой ссылки
   - `GET /links/{short_code}` – перенаправление на исходный URL
   - `DELETE /links/{short_code}` – удаление ссылки
   - `PUT /links/{short_code}` – изменение URL

2. **Статистика**:
   - `GET /links/{short_code}/stats` – просмотр данных о ссылке (исходный URL, дата создания, количество переходов, последнее использование)

3. **Пользовательские ссылки**:
   - Возможность задать свой уникальный короткий адрес через параметр custom_alias

4. **Поиск**:
   - `GET /links/search?original_url={url}` – поиск по исходному URL

5. **Срок действия**:
   - Установка времени жизни ссылки через параметр expires_at

### Дополнительно:

1. **Автоочистка**:
   - `DELETE /links/cleanup?days={days}` – удаление ссылок без активности за указанный период

2. **История**:
   - `GET /links/expired` – список истекших ссылок

3. **Группировка ссылок по проектам**:
   - Создание проектов для организации ссылок
   - Добавление/удаление ссылок в проектах
   - Просмотр всех ссылок в проекте

4. **Создание ссылок для незарегистрированных пользователей**:
   - Возможность сокращать ссылки без авторизации
   - Доступ к статистике для всех пользователей

## Технологии

- FastAPI
- PostgreSQL
- Redis
- JWT

## Как запустить

### Docker:

1. Запустите:
   ```
   docker-compose up -d
   ```

2. Откройте: http://localhost:8000


### Локально:
1. Установите зависимости:
   ```
   pip install -r requirements.txt
   ```

3. Настройте переменные среды:
   ```
   export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/url_shortener
   export REDIS_URL=redis://localhost:6379/0
   export SECRET_KEY=секретный_ключ
   export ALGORITHM=HS256
   export ACCESS_TOKEN_EXPIRE_MINUTES=30
   ```

4. Запустите:
   ```
   cd app
   uvicorn main:app --reload
   ```

5. Откройте: http://localhost:8000

## Документация API

После запуска доступна по адресам:
- Swagger: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Примеры

### Регистрация

```bash
curl -X 'POST' \
  'http://localhost:8000/register' \
  -H 'Content-Type: application/json' \
  -d '{
  "username": "user123",
  "email": "user@example.com",
  "password": "secure_password"
}'
```

### Авторизация

```bash
curl -X 'POST' \
  'http://localhost:8000/token' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'username=user123&password=secure_password'
```

### Создание ссылки (авторизованный пользователь)

```bash
curl -X 'POST' \
  'http://localhost:8000/links/shorten' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer ВАШ_ТОКЕН' \
  -d '{
  "original_url": "https://example.com/очень/длинный/адрес",
  "custom_alias": "пример",
  "expires_at": "2023-12-31T23:59:59"
}'
```

### Создание ссылки (без авторизации)

```bash
curl -X 'POST' \
  'http://localhost:8000/links/shorten' \
  -H 'Content-Type: application/json' \
  -d '{
  "original_url": "https://example.com/длинный/адрес/для/гостя",
  "custom_alias": "гостевая",
  "expires_at": "2023-12-31T23:59:59"
}'
```

### Просмотр статистики

```bash
curl -X 'GET' \
  'http://localhost:8000/links/пример/stats' \
  -H 'accept: application/json'
```

### Создание проекта

```bash
curl -X 'POST' \
  'http://localhost:8000/projects/' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer ВАШ_ТОКЕН' \
  -d '{
  "name": "Личные ссылки",
  "description": "Мои важные ссылки"
}'
```

### Добавление ссылки в проект

```bash
curl -X 'POST' \
  'http://localhost:8000/links/{link_id}/add-to-project/{project_id}' \
  -H 'Authorization: Bearer ВАШ_ТОКЕН'
```

## Структура БД

### Таблица users

| Поле           | Тип      | Описание                      |
|----------------|----------|-------------------------------|
| id             | Integer  | ID пользователя               |
| username       | String   | Имя пользователя              |
| email          | String   | Email                         |
| hashed_password| String   | Хеш пароля                    |
| is_active      | Boolean  | Статус активности             |
| is_admin       | Boolean  | Права администратора          |
| created_at     | DateTime | Дата регистрации              |

### Таблица projects

| Поле           | Тип      | Описание                      |
|----------------|----------|-------------------------------|
| id             | Integer  | ID проекта                    |
| name           | String   | Название проекта              |
| description    | Text     | Описание проекта              |
| created_at     | DateTime | Дата создания                 |
| user_id        | Integer  | ID владельца проекта          |

### Таблица links

| Поле           | Тип      | Описание                      |
|----------------|----------|-------------------------------|
| id             | Integer  | ID ссылки                     |
| original_url   | Text     | Исходный URL                  |
| short_code     | String   | Короткий код                  |
| created_at     | DateTime | Дата создания                 |
| last_used_at   | DateTime | Последнее использование       |
| expires_at     | DateTime | Срок действия                 |
| clicks         | Integer  | Счетчик переходов             |
| user_id        | Integer  | ID создателя (NULL для гостей)|
| project_id     | Integer  | ID проекта (если в проекте)   |