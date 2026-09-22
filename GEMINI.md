# Gemini Agent Guide: Microservices Blog Platform

This file documents the architecture, directory structure, operational commands, and coding standards for the Gemini AI agent working on this repository.

---

## 1. Architecture Overview

The system is designed as a decoupled, resilient microservices blog platform built with Python 3, FastAPI, and SQLite (following the **Database-per-Service** pattern).

```
                            [ Client / Browser ]
                                     │
                                     ▼
                     ┌───────────────────────────────┐
                     │   API Gateway (Port 8000)     │
                     └─┬──────────┬──────────┬─────┬─┘
                       │          │          │     │
         ┌─────────────┘          │          │     └─────────────┐
         ▼                        ▼          ▼                   ▼
┌──────────────────┐    ┌─────────────────┐  ┌─────────────────┐ ┌─────────────────┐
│   User Service   │    │  Blog Service   │  │ Comment Service │ │ Payment Service │
│   (Port 8001)    │    │   (Port 8002)   │  │   (Port 8003)   │ │   (Port 8004)   │
│   data/user.db   │    │   data/blog.db  │  │ data/comment.db │ │ data/payment.db │
└──────────────────┘    └─────────────────┘  └─────────────────┘ └─────────────────┘
```

### Microservice Port Map & Responsibilities

| Service | Port | Database | Primary Responsibility |
| :--- | :--- | :--- | :--- |
| **API Gateway** | `8000` | N/A | Central routing, unified Swagger docs, aggregated `/health`, token inspection |
| **User Service** | `8001` | `data/user.db` | User registration, login, PBKDF2 password hashing, JWT creation & verification |
| **Blog Service** | `8002` | `data/blog.db` | Post CRUD, slug generation, tags, pagination, premium content gating |
| **Comment Service**| `8003` | `data/comment.db`| Comments & threaded replies on posts, author moderation |
| **Payment Service**| `8004` | `data/payment.db`| Digital wallet balances, top-ups, author tipping, premium post unlock |

---

## 2. Directory Structure

```
blog/
├── data/                      # Isolated SQLite databases (gitignored/auto-created)
│   ├── user.db
│   ├── blog.db
│   ├── comment.db
│   └── payment.db
├── services/
│   ├── gateway/               # Central API Gateway & composite endpoints
│   │   ├── __init__.py
│   │   └── main.py
│   ├── user/                  # User & Auth microservice
│   │   ├── __init__.py
│   │   ├── database.py
│   │   ├── models.py
│   │   ├── routes.py
│   │   └── main.py
│   ├── blog/                  # Blog post management microservice
│   │   ├── __init__.py
│   │   ├── database.py
│   │   ├── models.py
│   │   ├── routes.py
│   │   └── main.py
│   ├── comment/               # Discussion & comments microservice
│   │   ├── __init__.py
│   │   ├── database.py
│   │   ├── models.py
│   │   ├── routes.py
│   │   └── main.py
│   └── payment/               # Wallet, tipping & paywall microservice
│       ├── __init__.py
│       ├── database.py
│       ├── models.py
│       ├── routes.py
│       └── main.py
├── shared/                    # Reusable cross-cutting contracts & utilities
│   ├── __init__.py
│   ├── config.py              # Central ports, URLs, secrets & paths
│   ├── schemas.py             # Generic APIResponse & HealthResponse
│   └── security.py            # Password hashing & HS256 JWT tokens
├── tests/                     # Microservice test suite
│   ├── __init__.py
│   └── test_services.py
├── docker-compose.yml         # Containerized multi-service deployment
├── Dockerfile                 # Microservices container image definition
├── main.py                    # Root entrypoint exporting gateway app
├── requirements.txt           # Python package requirements
├── run_services.py            # Concurrent local service runner with graceful exit
└── GEMINI.md                  # This file
```

---

## 3. Development Commands

### Running Locally (All Services)
Run the concurrent runner which boots all 4 services and the API Gateway:
```bash
./run_services.py
# or
python3 run_services.py
```

### Running an Individual Service
Each service can be launched independently (activate `.venv` first if needed: `source .venv/bin/activate`):
```bash
# Example: Run User Service only
uvicorn services.user.main:app --port 8001 --reload

# Example: Run Blog Service only
uvicorn services.blog.main:app --port 8002 --reload

# Example: Run API Gateway
uvicorn services.gateway.main:app --port 8000 --reload
```

### Running Automated Tests
```bash
python3 -m unittest discover -s tests -p "test_*.py" -v
```

### Docker Deployment
```bash
docker compose up --build
```

---

## 4. API Endpoints Quick Reference

### Gateway Routes (`http://localhost:8000`)
- **Interactive OpenAPI UI**: `GET /docs`
- **System Health Status**: `GET /health` (Aggregates status across all 4 microservices)
- **Composite Post Feed**: `GET /api/feed/post/{id}` (Aggregates post, author, comments & unlock status)

### User Service (`/api/users` via Gateway or `:8001` directly)
- `POST /register`: Register new user (`username`, `email`, `password`, `full_name`, `bio`)
- `POST /login`: Authenticate and receive JWT token
- `GET /me`: Authenticated profile (Requires `Authorization: Bearer <token>`)
- `GET /{user_id}`: Public user details

### Blog Service (`/api/posts` via Gateway or `:8002` directly)
- `GET /posts`: List published posts (supports `author_id`, `tag`, `limit`, `offset`)
- `POST /posts`: Create post (Requires Bearer token)
- `GET /posts/{id}`: Post details
- `PUT /posts/{id}`: Update post (Author only)
- `DELETE /posts/{id}`: Delete post (Author only)

### Comment Service (`/api/comments` via Gateway or `:8003` directly)
- `POST /comments`: Add comment or threaded reply
- `GET /posts/{post_id}/comments`: Nested comment thread for post
- `DELETE /comments/{id}`: Delete comment (Author only)

### Payment Service (`/api/payments` via Gateway or `:8004` directly)
- `GET /wallet`: Get logged-in user's balance
- `POST /topup`: Top up wallet (`amount`, `payment_method`)
- `POST /tip`: Tip author (`recipient_user_id`, `amount`, `note`)
- `POST /unlock-post`: Pay to unlock premium post (`post_id`)
- `GET /access/{post_id}`: Check if logged-in user has access
- `GET /transactions`: User transaction history

---

## 5. Architectural & Coding Rules for Agents

1. **Strict Microservice Decoupling**:
   - **Never** perform cross-database SQL queries or import another service's `database.py`.
   - Each service **must** only read/write to its own designated database (`user.db`, `blog.db`, `comment.db`, `payment.db`).
   - Cross-domain validation (e.g. verifying a user or post exists) must be performed via asynchronous HTTP calls using `httpx`.

2. **Standard Envelopes**:
   - All API endpoints should return data wrapped in `APIResponse[T]` defined in [schemas.py](file:///Users/yindiesh/Desktop/yindeish-git/blog/shared/schemas.py).

3. **Authentication Propagation**:
   - The API Gateway checks incoming `Authorization: Bearer <token>` and injects an `X-User-Id` header to downstream services.
   - Downstream services accept both direct Bearer tokens (for standalone execution) and the `X-User-Id` header (when behind the Gateway).

4. **Self-Contained Dependencies**:
   - Keep dependencies lean. SQLite and pure-Python crypto implementations avoid compilation issues across deployment targets.
