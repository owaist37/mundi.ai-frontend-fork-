#!/usr/bin/env python3
"""
Simple script to run the frontend-only Mundi application
"""
import uvicorn
import os

if __name__ == "__main__":
    # Set default auth mode if not specified
    if "MUNDI_AUTH_MODE" not in os.environ:
        os.environ["MUNDI_AUTH_MODE"] = "edit"
    
    print("Starting Mundi Frontend-Only Server...")
    print("This serves the React application with basic auth mock.")
    print("The frontend will need to be configured to connect to a separate backend API.")
    print()
    print("Frontend will be available at: http://localhost:8000")
    print()
    
    uvicorn.run(
        "src.wsgi:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )