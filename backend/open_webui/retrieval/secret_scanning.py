import re
import logging
import os
from typing import List, Dict, Any

log = logging.getLogger(__name__)

# Конфигурация: RAG_SECRET_SCANNING_MODE (warn/block/off)
SECRET_SCANNING_MODE = os.getenv('RAG_SECRET_SCANNING_MODE', 'warn').lower()

# Массив шаблонов для выявления секретов
SECRET_PATTERNS = [
    # AWS Access Key ID
    (r'AKIA[0-9A-Z]{16}', 'AWS Access Key ID', 'Выявлен AWS Access Key ID'),
    # GitHub Personal Access Token (ghp_, gho_, ghu_, ghs_, ghr_)
    (r'ghp_[a-zA-Z0-9_]{20,}', 'GitHub Personal Access Token', 'Выявлен GitHub Personal Access Token (ghp_)'),
    (r'gho_[a-zA-Z0-9_]{22,}', 'GitHub OAuth Token', 'Выявлен GitHub OAuth Token (gho_)'),
    (r'ghu_[a-zA-Z0-9_]{22,}', 'GitHub User Token', 'Выявлен GitHub User Token (ghu_)'),
    (r'ghs_[a-zA-Z0-9_]{20,}', 'GitHub Server-to-Server Token', 'Выявлен GitHub Server-to-Server Token (ghs_)'),
    (r'ghr_[a-zA-Z0-9_]{20,}', 'GitHub Refresh Token', 'Выявлен GitHub Refresh Token (ghr_)'),
    # Slack Tokens (xoxb, xoxp, xoxa)
    (r'xoxb-[0-9A-Za-z-]+-[0-9A-Za-z-]+', 'Slack Bot Token', 'Выявлен Slack Bot Token'),
    (r'xoxp-[0-9A-Za-z-]+-[0-9A-Za-z-]+', 'Slack User Token', 'Выявлен Slack User Token'),
    (r'xoxa-[0-9A-Za-z-]+-[0-9A-Za-z-]+', 'Slack App Token', 'Выявлен Slack App Token'),
    # GitHub App Token (xoxb with more parts)
    (r'xoxb-[0-9A-Za-z-]+-[0-9A-Za-z-]+-[0-9A-Za-z-]+', 'GitHub App Token', 'Выявлен GitHub App Token'),
    # JWT Tokens
    (r'eyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}', 'JWT Token', 'Выявлен JWT токен'),
    # Google API Keys
    (r'AIza[0-9A-Za-z_-]{35}', 'Google API Key', 'Выявлен Google API ключ'),
    # Stripe Keys
    (r'sk_live_[a-zA-Z0-9]{24}', 'Stripe Live Secret Key', 'Выявлен Stripe Live Secret Key'),
    (r'sk_test_[a-zA-Z0-9]{24}', 'Stripe Test Secret Key', 'Выявлен Stripe Test Secret Key'),
    # Twilio API Keys
    (r'AC[0-9a-fA-F]{32}', 'Twilio Account SID', 'Выявлен Twilio Account SID'),
    (r'HW[0-9a-fA-F]{32}', 'Twilio API Key SID', 'Выявлен Twilio API Key SID'),
    # AWS Secret Access Key (40 chars base64-like)
    (r'[A-Za-z0-9/+=]{40}', 'AWS Secret Access Key', 'Потенциальный AWS Secret Access Key'),
    # Private Keys
    (r'-----BEGIN RSA PRIVATE KEY-----', 'RSA Private Key', 'Выявлена RSA приватная ключ'),
    (r'-----BEGIN OPENSSH PRIVATE KEY-----', 'OpenSSH Private Key', 'Выявлен OpenSSH приватный ключ'),
    (r'-----BEGIN EC PRIVATE KEY-----', 'EC Private Key', 'Выявлен EC приватный ключ'),
    (r'-----BEGIN PGP PRIVATE KEY Block-----', 'PGP Private Key', 'Выявлен PGP приватный ключ'),
    # Generic API Keys in JSON
    (r'(?i)["\']api[_-]?key["\']\s*:\s*["\'][^"\']{10,}["\']', 'API Key in JSON', 'Выявлен ключ API в JSON'),
    (r'(?i)["\']secret["\']\s*:\s*["\'][^"\']{10,}["\']', 'Secret in JSON', 'Выявлен секрет в JSON'),
    # Database Connection Strings
    (r'(?i)\b(postgres|mysql|mongodb|redis):\/\/[^\s]+:[^\s]+@', 'Database Connection String', 'Выявлена строка подключения БД'),
    # OAuth Client Secrets
    (r'(?i)client[_-]?secret\s*=\s*[a-zA-Z0-9_]{20,}', 'OAuth Client Secret', 'Выявлен OAuth клиентский секрет'),
    # Heroku API Key
    (r'(?i)heroku[_-]?api[_-]?key\s*=\s*[a-zA-Z0-9_]{20,}', 'Heroku API Key', 'Выявлен Heroku API ключ'),
    # Telegram Bot Token
    (r'\d+:[a-zA-Z0-9_-]{30,}', 'Telegram Bot Token', 'Выявлен Telegram Bot токен'),
    # AWS Session Token
    (r'AWSTrking[a-zA-Z0-9_]{20,}', 'AWS Session Token', 'Выявлен AWS Session Token'),
]


class SecretScanner:
    """Сканер контента файлов на наличие чувствительных данных."""

    def __init__(self, mode: str = 'warn'):
        """
        Args:
            mode: Режим работы - 'warn' (предупреждать), 'block' (блокировать), 'off' (отключить)
        """
        self.mode = mode.lower()
        if self.mode not in ('warn', 'block', 'off'):
            self.mode = 'warn'

    def scan_content(self, content: str, filename: str = "file") -> List[Dict[str, Any]]:
        """
        Сканирует содержимое файла на наличие секретов.
        
        Args:
            content: Строка контента файла
            filename: Имя файла (для информации)
            
        Returns:
            Список найденных данных с типом, описанием и данными о позиции
        """
        if self.mode == 'off':
            return []

        findings = []
        for pattern, secret_type, description in SECRET_PATTERNS:
            regex = re.compile(pattern, re.IGNORECASE)
            for match in regex.finditer(content):
                # Извлекаем найденный секрет (обрезанный для безопасности)
                found_secret = match.group(0)
                # Обрезаем если слишком длинный
                if len(found_secret) > 20:
                    found_secret = found_secret[:10] + "..." + found_secret[-5:]
                
                finding = {
                    'type': secret_type,
                    'description': description,
                    'pattern': pattern,
                    'position': match.start(),
                    'length': len(match.group(0)),
                    'found_secret': found_secret,
                    'filename': filename
                }
                findings.append(finding)

        return findings

    def scan_file_path(self, file_path: str) -> List[Dict[str, Any]]:
        """
        Сканирует содержимое файла (по пути) на наличие секретов.
        
        Args:
            file_path: Полный путь к файлу
            
        Returns:
            Список найденных данных
        """
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            return self.scan_content(content, os.path.basename(file_path))
        except Exception as e:
            log.error(f"Ошибка при чтении файла {file_path}: {e}")
            return []

    def should_block(self, findings: List[Dict[str, Any]]) -> bool:
        """
        Определяет, следует ли блокировать операцию на основе найденных данных.
        
        Args:
            findings: Список найденных данных
            
        Returns:
            True если найденные данные требуют блокировки
        """
        if self.mode == 'off':
            return False
        if self.mode == 'block' and findings:
            return True
        return False

    def format_findings(self, findings: List[Dict[str, Any]]) -> str:
        """
        Форматирует список найденных данных в читаемое сообщение.
        
        Args:
            findings: Список найденных данных
            
        Returns:
            Текст сообщения
        """
        if not findings:
            return "Секретов не обнаружено."

        lines = [f"Обнаружено {len(findings)} потенциальных уязвимостей:", ""]
        for i, finding in enumerate(findings, 1):
            lines.append(f"{i}. {finding['type']}: {finding['description']}")
            if len(findings) <= 20:  # Limit detailed output
                lines.append(f"   Найдено: {finding['found_secret']}")
                lines.append(f"   Позиция: {finding['position']}-{finding['position']+len(finding['found_secret'])}")
            lines.append("")
        
        return "\n".join(lines)


# Глобальный экземпляр
_scanner = None

def get_secret_scanner() -> SecretScanner:
    """Получить глобальный экземпляр сканера."""
    global _scanner
    if _scanner is None:
        _scanner = SecretScanner(SECRET_SCANNING_MODE)
    return _scanner


def scan_file_content(content: str, filename: str = "file") -> List[Dict[str, Any]]:
    """Функция удобного вызова сканирования."""
    return get_secret_scanner().scan_content(content, filename)


def scan_file_path_by_path(file_path: str) -> List[Dict[str, Any]]:
    """Функция удобного вызова сканирования по пути."""
    return get_secret_scanner().scan_file_path(file_path)
