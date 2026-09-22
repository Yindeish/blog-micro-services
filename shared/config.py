import os
from pathlib import Path

# Base directory
BASE_DIR = Path(__file__).resolve().parent.parent

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

# Supabase Configuration
SUPABASE_URL = os.getenv("SUPABASE_URL", os.getenv("NEXT_PUBLIC_SUPABASE_URL", "https://lygxpdtegrpwaqmthicc.supabase.co"))
SUPABASE_KEY = os.getenv("SUPABASE_KEY", os.getenv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "sb_publishable_Hdlt9-z_E7M66g-sPiQ3Cg_7eP2ApqU"))
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

# Squad Payment Gateway Configuration
SQUAD_BASE_URL = os.getenv("SQUAD_BASE_URL", "https://api-d.squadco.com")
SQUAD_SECRET_KEY = os.getenv("SQUAD_SECRET_KEY", "sk_70b3d63fe856f4da6f564a248c14338a3c4d9d0f")
SQUAD_PUBLIC_KEY = os.getenv("SQUAD_PUBLIC_KEY", "pk_70b3d63fe856f4da165c4c2399642cfa3d38821c")
