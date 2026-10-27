import base64
import os
import random
import sys
from pathlib import Path
from typing import Annotated

import typer
import uvicorn

app = typer.Typer()

KEY_FILE_ENV = 'WEBUI_SECRET_KEY_FILE'
DEFAULT_KEY_FILE = 'data/.webui_secret_key'
DEFAULT_SECRET_KEY_LENGTH = 24


def version_callback(value: bool) -> None:
    if value:
        from open_webui.env import VERSION

        typer.echo(f'Open WebUI version: {VERSION}')
        raise typer.Exit()


@app.command()
def main(
    version: Annotated[bool | None, typer.Option('--version', callback=version_callback)] = None,
):
    pass


@app.command()
def serve(
    host: str = '0.0.0.0',
    port: int = 8080,
):
    os.environ['FROM_INIT_PY'] = 'true'
    if os.getenv('WEBUI_SECRET_KEY') is None:
        typer.echo('Loading WEBUI_SECRET_KEY from file, not provided as an environment variable.')
        # Resolved here, not at module level: the app's .env (which may
        # override WEBUI_SECRET_KEY_FILE) is only loaded once open_webui.env
        # imports, and the default path lives in the persistent data volume so
        # the key survives `docker compose down`.
        key_file = Path(os.getenv(KEY_FILE_ENV, DEFAULT_KEY_FILE))
        if not key_file.exists():
            key_length = int(os.getenv('WEBUI_SECRET_KEY_LENGTH', DEFAULT_SECRET_KEY_LENGTH))
            if key_length < 1:
                raise ValueError('WEBUI_SECRET_KEY_LENGTH must be a positive integer')
            typer.echo(f'Generating a new secret key and saving it to {key_file}')
            key_file.parent.mkdir(parents=True, exist_ok=True)
            key_file.write_bytes(base64.b64encode(random.randbytes(key_length)))
        typer.echo(f'Loading WEBUI_SECRET_KEY from {key_file}')
        os.environ['WEBUI_SECRET_KEY'] = key_file.read_text()

    if os.getenv('USE_CUDA_DOCKER', 'false') == 'true':
        typer.echo('CUDA is enabled, appending LD_LIBRARY_PATH to include torch/cudnn & cublas libraries.')
        LD_LIBRARY_PATH = os.getenv('LD_LIBRARY_PATH', '').split(':')
        os.environ['LD_LIBRARY_PATH'] = ':'.join(
            LD_LIBRARY_PATH
            + [
                '/usr/local/lib/python3.11/site-packages/torch/lib',
                '/usr/local/lib/python3.11/site-packages/nvidia/cudnn/lib',
            ]
        )
        try:
            import torch

            assert torch.cuda.is_available(), 'CUDA not available'
            typer.echo('CUDA seems to be working')
        except Exception as e:
            typer.echo(
                'Error when testing CUDA but USE_CUDA_DOCKER is true. '
                'Resetting USE_CUDA_DOCKER to false and removing '
                f'LD_LIBRARY_PATH modifications: {e}'
            )
            os.environ['USE_CUDA_DOCKER'] = 'false'
            os.environ['LD_LIBRARY_PATH'] = ':'.join(LD_LIBRARY_PATH)

    import open_webui.main  # noqa: F401
    from open_webui.env import UVICORN_WORKERS  # Import the workers setting

    # On Windows, uvicorn's default loop factory hardcodes ProactorEventLoop,
    # which is incompatible with psycopg v3 async.  Setting loop='none' lets
    # asyncio.run() respect the WindowsSelectorEventLoopPolicy set in db.py.
    loop = 'none' if sys.platform == 'win32' else 'auto'

    uvicorn.run(
        'open_webui.main:app',
        host=host,
        port=port,
        forwarded_allow_ips='*',
        workers=UVICORN_WORKERS,
        loop=loop,
    )


@app.command()
def dev(
    host: str = '0.0.0.0',
    port: int = 8080,
    reload: bool = True,
):
    uvicorn.run(
        'open_webui.main:app',
        host=host,
        port=port,
        reload=reload,
        forwarded_allow_ips='*',
    )


if __name__ == '__main__':
    app()
