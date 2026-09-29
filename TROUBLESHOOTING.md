# Open WebUI Troubleshooting Guide

## Understanding the Open WebUI Architecture

The Open WebUI system is designed to streamline interactions between the client (your browser) and the Ollama API. At the heart of this design is a backend reverse proxy, enhancing security and resolving CORS issues.

- **How it Works**: The Open WebUI is designed to interact with the Ollama API through a specific route. When a request is made from the WebUI to Ollama, it is not directly sent to the Ollama API. Initially, the request is sent to the Open WebUI backend via `/ollama` route. From there, the backend is responsible for forwarding the request to the Ollama API. This forwarding is accomplished by using the route specified in the `OLLAMA_BASE_URL` environment variable. Therefore, a request made to `/ollama` in the WebUI is effectively the same as making a request to `OLLAMA_BASE_URL` in the backend. For instance, a request to `/ollama/api/tags` in the WebUI is equivalent to `OLLAMA_BASE_URL/api/tags` in the backend.

- **Security Benefits**: This design prevents direct exposure of the Ollama API to the frontend, safeguarding against potential CORS (Cross-Origin Resource Sharing) issues and unauthorized access. Requiring authentication to access the Ollama API further enhances this security layer.

## Open WebUI: Server Connection Error

If you're experiencing connection issues, it’s often due to the WebUI docker container not being able to reach the Ollama server at 127.0.0.1:11434 (host.docker.internal:11434) inside the container . Use the `--network=host` flag in your docker command to resolve this. Note that the port changes from 8083 to 8080, resulting in the link: `http://localhost:8080`.

**Example Docker Command**:

```bash
docker run -d --network=host -v open-webui:/app/backend/data -e OLLAMA_BASE_URL=http://127.0.0.1:11434 --name open-webui --restart always ghcr.io/open-webui/open-webui:main
```

### Error on Slow Responses for Ollama

Open WebUI has a default timeout of 5 minutes for Ollama to finish generating the response. If needed, this can be adjusted via the environment variable AIOHTTP_CLIENT_TIMEOUT, which sets the timeout in seconds.

### General Connection Errors

**Ensure Ollama Version is Up-to-Date**: Always start by checking that you have the latest version of Ollama. Visit [Ollama's official site](https://ollama.com/) for the latest updates.

**Troubleshooting Steps**:

1. **Verify Ollama URL Format**:
   - When running the Web UI container, ensure the `OLLAMA_BASE_URL` is correctly set. (e.g., `http://192.168.1.1:11434` for different host setups).
   - In the Open WebUI, navigate to "Settings" > "General".
   - Confirm that the Ollama Server URL is correctly set to `[OLLAMA URL]` (e.g., `http://localhost:11434`).

By following these enhanced troubleshooting steps, connection issues should be effectively resolved. For further assistance or queries, feel free to reach out to us on our community Discord.

## Knowledge Base / Embedding Issues

**Upload stuck at "Uploading 0%" or file frozen in `processing`:** uploads and embedding now report progress over SSE and every embedding HTTP call has a deadline, so a wedged embedding server fails the job with the reason recorded on the file instead of hanging indefinitely. Refresh the page — live progress is reconciled via the pending-files poll; a failed upload drops its row rather than leaving a frozen one.

**`503 server busy, maximum pending requests exceeded` from Ollama (embeddings):** the document's batches were flooding the embedding server. The default embedding batch size is `1` chunk per request and concurrent embedding requests are bounded (`RAG_EMBEDDING_CONCURRENT_REQUESTS`, fallback limit `4` when left at `0`). Raise both only for a GPU-backed or hosted embedding endpoint (Admin → Settings → RAG, or declare them in `.env`).

**Cancellation seems to do nothing / cancelled file reappears as completed:** cancellation is cooperative and checked at each pipeline checkpoint (before processing, around the embedding step, before auto-linking); vectors already written for a cancelled file are cleaned up. Make sure the running image includes this fix — older builds removed the record while the background pipeline kept going and re-linked the file.

**Same document embedded twice:** duplicate detection (`RAG_DEDUP_DUPLICATE_FILES`, on by default) copies vectors from an already-indexed file whose extracted-text hash matches, provided the embedding engine and model match. Collections created before this fix may contain re-split chunks that refuse reuse — re-add the file to rebuild them.

### Deployment settings come from `.env`

For containerized runs, `.env` in the repository root is the single source of deployment settings: it is mounted into the container, parsed by `backend/start.sh`, and re-read by `open_webui/env.py`, which ranks names declared there **above** the stored `config` table. If a setting (e.g. `VECTOR_DB`, `VALKEY_URL`, `rag.embedding_batch_size`) appears ignored:

1. Check whether the name is declared in `.env` — if yes, the file wins after every restart, and Admin → Settings edits apply only until the next restart.
2. Do not duplicate these names in `docker-compose.yaml` `environment:` blocks — the compose files intentionally omit them.
3. Use a different file with `ENV_FILE=.env.staging docker compose up -d`.

### Container restarts endlessly / UI never comes up

A `restart: always` deployment converts a startup failure into a silent crash-loop: the container repeatedly starts, dies, and restarts, so the UI stays down while the logs fill with the same traceback. The most common cause is `VECTOR_DB=valkey` declared in `.env`:

- `backend/requirements.txt` lists `valkey-glide-sync` as an *optional* dependency (it is commented out), so a stock image does not have it. At startup `open_webui/retrieval/vector/factory.py` builds the client for the configured backend, and `retrieval/vector/dbs/valkey.py` raises `ImportError: valkey-glide-sync is required when VECTOR_DB=valkey`.
- A declared but unreachable Valkey server breaks indexing the same way from the runtime side.

Diagnose with `docker logs <container> --tail 40`; if the traceback ends in that `ImportError`, comment `VECTOR_DB`/`VALKEY_URL` out in `.env` and restart — the default (`chroma`) keeps indexes in the `data` volume. To actually use Valkey, install the client (`pip install valkey-glide-sync==2.3.1`) into the image *and* run a Valkey server first.
