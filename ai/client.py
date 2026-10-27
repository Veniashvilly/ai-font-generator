
import os
from pathlib import Path

from dotenv import load_dotenv
from gigachat import GigaChat


# Корневая папка нашего проекта.
BASE_DIR = Path(__file__).resolve().parent.parent

# Загружаем переменные окружения из .env.
load_dotenv(BASE_DIR / ".env")


def ask_gigachat(prompt: str) -> str:
    """
    Отправляет запрос в GigaChat и возвращает
    текстовый ответ нейросети.
    """

    # Получаем API-ключ.
    credentials = os.getenv("GIGACHAT_CREDENTIALS")

    if not credentials:
        raise ValueError(
            "Не найден GIGACHAT_CREDENTIALS в .env"
        )

    # Получаем название модели и область доступа.
    model = os.getenv("GIGACHAT_MODEL", "GigaChat-2")
    scope = os.getenv(
        "GIGACHAT_SCOPE",
        "GIGACHAT_API_PERS"
    )

    # Получаем путь к доверенному сертификату.
    ca_bundle = os.getenv("GIGACHAT_CA_BUNDLE_FILE")

    if not ca_bundle:
        raise ValueError(
            "Не указан GIGACHAT_CA_BUNDLE_FILE в .env"
        )

    # Проверяем наличие файла сертификата.
    certificate_path = Path(ca_bundle)

    if not certificate_path.is_file():
        raise FileNotFoundError(
            f"Файл сертификата не найден: {certificate_path}"
        )

    print("\nПодключаемся к GigaChat...")

    # Создаём клиент GigaChat.
    # ca_bundle_file задаёт доверенный сертификат.
    # Проверка SSL остаётся включённой.
    with GigaChat(
        credentials=credentials,
        scope=scope,
        model=model,
        ca_bundle_file=str(certificate_path),
        verify_ssl_certs=True,
        timeout=60
    ) as client:

        # Отправляем текстовый запрос нейросети.
        response = client.chat(prompt)

        # Извлекаем ответ из результата API.
        answer = response.choices[0].message.content

        if not answer:
            raise ValueError(
                "GigaChat вернул пустой ответ"
            )

        print("Ответ от GigaChat получен!")

        return answer


# Совместимость с нашим модулем designer.py.
def ask(prompt: str) -> str:
    return ask_gigachat(prompt)
