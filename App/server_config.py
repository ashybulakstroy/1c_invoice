"""Read web binding from the project's .env without exposing unrelated settings."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ServerSettings:
    host: str
    port: int

    @property
    def browser_url(self):
        host = '127.0.0.1' if self.host in {'0.0.0.0', '::'} else self.host
        if ':' in host and not host.startswith('['):
            host = f'[{host}]'
        return f'http://{host}:{self.port}'


def server_settings(env_path=ROOT / '.env', environ=None):
    values = {**dotenv_values(env_path, encoding='utf-8-sig'), **(os.environ if environ is None else environ)}
    host = str(values.get('OCR_WEB_HOST') or '0.0.0.0').strip()
    if not host or any(character.isspace() for character in host) or '://' in host or '/' in host:
        raise ValueError('OCR_WEB_HOST: укажите IP-адрес или имя хоста без http:// и пути')
    try:
        port = int(values.get('OCR_WEB_PORT') or '8023')
    except (ValueError, TypeError) as error:
        raise ValueError('OCR_WEB_PORT: требуется целое число от 1 до 65535') from error
    if not 1 <= port <= 65535:
        raise ValueError('OCR_WEB_PORT: требуется целое число от 1 до 65535')
    return ServerSettings(host, port)
