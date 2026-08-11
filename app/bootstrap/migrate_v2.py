"""
Migration v2.0 — Iatch Axiom
Adiciona: data_promessa, cob_promessas_quebradas, cob_logs atualizado
"""
import sqlite3, os, sys

DB_PATH = os.path.join(os.path.dirname(__file__), '../../cobranca_local.db')
DB_PATH = os.path.abspath(DB_PATH)

def run():
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()

    print(f"[migrate_v2] Banco: {DB_PATH}")

    # ── 1. Adiciona data_promessa em cob_interacoes ──────────────────────────
    try:
        cur.execute("ALTER TABLE cob_interacoes ADD COLUMN data_promessa TEXT")
        print("[OK] cob_interacoes.data_promessa adicionado")
    except sqlite3.OperationalError:
        print("[SKIP] cob_interacoes.data_promessa já existe")

    # ── 2. Adiciona nivel em cob_usuarios ────────────────────────────────────
    try:
        cur.execute("ALTER TABLE cob_usuarios ADD COLUMN nivel INTEGER DEFAULT 0")
        print("[OK] cob_usuarios.nivel adicionado")
    except sqlite3.OperationalError:
        print("[SKIP] cob_usuarios.nivel já existe")

    # ── 3. Adiciona aprovado em cob_usuarios ─────────────────────────────────
    try:
        cur.execute("ALTER TABLE cob_usuarios ADD COLUMN aprovado INTEGER DEFAULT 0")
        print("[OK] cob_usuarios.aprovado adicionado")
    except sqlite3.OperationalError:
        print("[SKIP] cob_usuarios.aprovado já existe")

    # ── 4. Aprovação automática do admin ─────────────────────────────────────
    cur.execute("""
        UPDATE cob_usuarios SET aprovado=1, nivel=99
        WHERE setor='Diretoria' AND aprovado=0
    """)
    print("[OK] Admin(s) Diretoria aprovados automaticamente")

    # ── 5. Tabela promessas quebradas ────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cob_promessas_quebradas (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            interacao_id  INTEGER NOT NULL,
            fn_areceber_id INTEGER NOT NULL,
            usuario_id    INTEGER NOT NULL,
            data_promessa TEXT NOT NULL,
            detectado_em  TEXT DEFAULT (datetime('now')),
            resolvido     INTEGER DEFAULT 0,
            resolvido_em  TEXT
        )
    """)
    print("[OK] cob_promessas_quebradas criada/verificada")

    # ── 6. Tabela log de acessos ─────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cob_log_acessos (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER,
            login      TEXT,
            acao       TEXT,
            ip         TEXT,
            user_agent TEXT,
            criado_em  TEXT DEFAULT (datetime('now'))
        )
    """)
    print("[OK] cob_log_acessos criada/verificada")

    conn.commit()
    conn.close()
    print("\n[migrate_v2] Concluído com sucesso.")

if __name__ == "__main__":
    run()
