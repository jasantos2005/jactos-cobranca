#!/usr/bin/env python3
"""
Bootstrap — cria tabelas SQLite e usuário admin inicial.
Execute UMA VEZ: python3 -m app.bootstrap.create_admin
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from app.core.db_local import db_local, local_query_one, local_execute
from app.core.security import hash_password

DDL = [
    """CREATE TABLE IF NOT EXISTS cob_usuarios (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        nome       TEXT NOT NULL,
        login      TEXT NOT NULL UNIQUE,
        senha_hash TEXT NOT NULL,
        setor      TEXT NOT NULL DEFAULT 'Financeiro',
        ativo      INTEGER NOT NULL DEFAULT 1,
        criado_em  TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
    """CREATE TABLE IF NOT EXISTS cob_permissoes (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id     INTEGER NOT NULL,
        dashboard_code TEXT NOT NULL,
        ativo          INTEGER NOT NULL DEFAULT 1,
        UNIQUE(usuario_id, dashboard_code),
        FOREIGN KEY (usuario_id) REFERENCES cob_usuarios(id)
    )""",
    """CREATE TABLE IF NOT EXISTS cob_interacoes (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        fn_areceber_id  INTEGER NOT NULL,
        usuario_id      INTEGER NOT NULL,
        acao            TEXT NOT NULL,
        obs             TEXT,
        pago            INTEGER NOT NULL DEFAULT 0,
        criado_em       TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (usuario_id) REFERENCES cob_usuarios(id)
    )""",
    """CREATE TABLE IF NOT EXISTS cob_logs (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER NOT NULL,
        acao       TEXT NOT NULL,
        ip         TEXT,
        criado_em  TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (usuario_id) REFERENCES cob_usuarios(id)
    )""",
]

DASHBOARD_CODES = [
    "COB_PAINEL", "COB_AGUARDANDO", "COB_PAGOS",
    "COB_DASHBOARD", "COB_ADMIN",
]

def main():
    print("=== Bootstrap Cliquedf — Cobrança ===\n")

    with db_local() as conn:
        for ddl in DDL:
            conn.execute(ddl)

    print("✅ Tabelas criadas / verificadas.")

    existing = local_query_one("SELECT id FROM cob_usuarios WHERE login = 'admin'")
    if not existing:
        uid = local_execute(
            "INSERT INTO cob_usuarios (nome, login, senha_hash, setor) VALUES (?,?,?,?)",
            ("Administrador", "admin", hash_password("Admin@1234"), "Diretoria")
        )
        for code in DASHBOARD_CODES:
            local_execute(
                "INSERT OR IGNORE INTO cob_permissoes (usuario_id, dashboard_code, ativo) VALUES (?,?,1)",
                (uid, code)
            )
        print("✅ Usuário admin criado.")
        print("   Login: admin | Senha: Admin@1234")
        print("⚠️  TROQUE A SENHA após o primeiro login!")
    else:
        print("ℹ️  Usuário admin já existe — ignorado.")

    print("\n[Bootstrap concluído]")

if __name__ == "__main__":
    main()
