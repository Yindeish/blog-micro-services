"""
Main Application Entry Point.
Exports the API Gateway as `app` for uvicorn deployment.
To run all microservices concurrently for local development, run:
    python run_services.py
"""

import uvicorn
from services.gateway.main import app
from shared.config import GATEWAY_PORT

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=GATEWAY_PORT, reload=True)