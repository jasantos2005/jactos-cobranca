#!/usr/bin/env python3
"""
Migration v3 — Automação de Cobrança via WhatsApp
Adiciona: cob_whatsapp_optout, cob_whatsapp_sessao, usuário de sistema bot_whatsapp

Execute UMA VEZ, de dentro de /opt/automacoes/cliquedf/cobranca:
    python3 -m app.bootstrap.migrate_v3_whatsapp

Este script NÃO altera nenhuma tabela existente (cob_interacoes, cob_usuarios, etc.),
apenas adiciona tabelas novas e um usuário novo. Seguro de rodar em produção.
"""
import sys, os, secrets

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from app.core.db_local import db_local, local_query_one, local_execute
from app.core.security import hash_senha as hash_password


def run():
    print("=== Migration v3 — WhatsApp Cobrança ===\n")

    with db_local() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cob_whatsapp_optout (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                fn_areceber_id  INTEGER,
                cliente_id      INTEGER,
                telefone        TEXT NOT NULL,
                criado_em       TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        print("[OK] cob_whatsapp_optout criada/verificada")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS cob_whatsapp_sessao (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                telefone          TEXT NOT NULL UNIQUE,
                fn_areceber_id    INTEGER,
                cliente_id        INTEGER,
                etapa             TEXT NOT NULL DEFAULT 'aguardando_identificacao',
                canal             TEXT NOT NULL DEFAULT 'texto',
                instance_origem   TEXT,
                cpf_candidato     TEXT,
                dados_extra       TEXT,
                criado_em         TEXT NOT NULL DEFAULT (datetime('now')),
                atualizado_em     TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        print("[OK] cob_whatsapp_sessao criada/verificada")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_optout_fn ON cob_whatsapp_optout(fn_areceber_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessao_tel ON cob_whatsapp_sessao(telefone)")
        print("[OK] Índices criados/verificados")

    existente = local_query_one("SELECT id FROM cob_usuarios WHERE login = 'bot_whatsapp'")
    if not existente:
        senha_aleatoria = secrets.token_urlsafe(24)
        uid = local_execute(
            "INSERT INTO cob_usuarios (nome, login, senha_hash, setor, ativo) VALUES (?,?,?,?,?)",
            ("Bot WhatsApp Cobrança", "bot_whatsapp", hash_password(senha_aleatoria), "Automação", 1)
        )
        print(f"[OK] Usuário 'bot_whatsapp' criado (id={uid})")
    else:
        print(f"[SKIP] Usuário 'bot_whatsapp' já existe (id={existente['id']})")

    print("\n[migrate_v3_whatsapp] Concluído com sucesso.")


if __name__ == "__main__":
    run()
