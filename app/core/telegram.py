import os
from dotenv import load_dotenv

load_dotenv(
    dotenv_path=os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        ".env",
    )
)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()

TELEGRAM_CHAT = os.getenv("TELEGRAM_CHAT", "").strip()

TELEGRAM_CHAT_PRIVADO = os.getenv(
    "TELEGRAM_CHAT_PRIVADO",
    "",
).strip()

TELEGRAM_CHAT_SERASA = os.getenv(
    "TELEGRAM_CHAT_SERASA",
    "",
).strip()

# Mantém compatibilidade com os módulos que trabalham
# com listas de destinatários.
TELEGRAM_CHATS = [TELEGRAM_CHAT] if TELEGRAM_CHAT else []

TELEGRAM_CHATS_PRIVADOS = (
    [TELEGRAM_CHAT_PRIVADO]
    if TELEGRAM_CHAT_PRIVADO
    else []
)


def telegram_url() -> str:
    if not TELEGRAM_TOKEN:
        raise RuntimeError(
            "TELEGRAM_TOKEN não configurado."
        )

    return (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_TOKEN}/sendMessage"
    )
