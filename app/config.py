from dotenv import load_dotenv
import os

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

class Settings:
    DB_HOST:     str = os.getenv("DB_HOST", "186.148.228.42")
    DB_PORT:     int = int(os.getenv("DB_PORT", 3306))
    DB_USER:     str = os.getenv("DB_USER", "escrita")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")
    DB_NAME:     str = os.getenv("DB_NAME", "ixcprovedor")

    SECRET_KEY:  str = os.getenv("SECRET_KEY", "mude-isso-em-producao")
    ALGORITHM:   str = os.getenv("ALGORITHM", "HS256")
    TOKEN_EXP:   int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 480))

    APP_TITLE:   str = os.getenv("APP_TITLE", "Cliquedf — Cobrança")
    APP_PORT:    int = int(os.getenv("APP_PORT", 8001))
    APP_ENV:     str = os.getenv("APP_ENV", "production")

settings = Settings()

IXC_API_URL   = os.getenv("IXC_API_URL", "")
IXC_API_USER  = os.getenv("IXC_API_USER", "")
IXC_API_TOKEN = os.getenv("IXC_API_TOKEN", "")
