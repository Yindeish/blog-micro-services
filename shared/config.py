import os
from pathlib import Path

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Service URLs
USER_SERVICE_URL = os.getenv("USER_SERVICE_URL", "http://127.0.0.1:8001")
BLOG_SERVICE_URL = os.getenv("BLOG_SERVICE_URL", "http://127.0.0.1:8002")
COMMENT_SERVICE_URL = os.getenv("COMMENT_SERVICE_URL", "http://127.0.0.1:8003")
PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL", "http://127.0.0.1:8004")

# Service Ports
GATEWAY_PORT = int(os.getenv("GATEWAY_PORT", "8000"))
USER_PORT = int(os.getenv("USER_PORT", "8001"))
BLOG_PORT = int(os.getenv("BLOG_PORT", "8002"))
COMMENT_PORT = int(os.getenv("COMMENT_PORT", "8003"))
PAYMENT_PORT = int(os.getenv("PAYMENT_PORT", "8004"))

# Security
JWT_SECRET = os.getenv("JWT_SECRET", "super-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_SECONDS = int(os.getenv("JWT_EXPIRATION_SECONDS", "86400"))  # 24 hours
