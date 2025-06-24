---
title: Local LLMs (Mistral) with Ollama
description: Using a local LLM allows complete data privacy and control. Mundi is compatible with models trained by Mistral, Europe's largest AI lab.
---

https://ollama.com/blog/openai-compatibility

--- a/docker-compose.yml
+++ b/docker-compose.yml
@@ -41,6 +41,9 @@ services:
       - POSTGRES_PASSWORD=gdalpassword
       - PYTHONUNBUFFERED=1
       - PYTHONIOENCODING=utf-8
+      # - OPENAI_BASE_URL=http://host.docker.internal:11434/v1
+      # - OPENAI_API_KEY=ollama
+      # - OPENAI_MODEL=orieg/gemma3-tools:1b
     command: uvicorn src.wsgi:app --host 0.0.0.0 --port 8000 --log-level debug --access-log --use-colors
     volumes:

in docker compose