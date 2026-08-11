from app.core.db_local import local_query, local_query_one, local_execute

GRUPO_NOMES = {1:'Operador', 2:'Supervisor', 3:'Gerente', 4:'Diretoria', 99:'Desenvolvimento'}

def get_menus_usuario(nivel: int) -> list:
    """Retorna lista de menus liberados para o grupo do usuário."""
    if nivel == 99:
        return local_query("SELECT * FROM cob_menus ORDER BY ordem", ())
    return local_query("""
        SELECT m.* FROM cob_menus m
        JOIN cob_permissoes_menu p ON p.menu_id = m.id
        WHERE p.grupo_id = ? AND p.ativo = 1
        ORDER BY m.ordem
    """, (nivel,))

def tem_permissao(nivel: int, codigo_menu: str) -> bool:
    """Verifica se o nível tem acesso a um menu específico."""
    if nivel == 99:
        return True
    r = local_query_one("""
        SELECT 1 FROM cob_permissoes_menu p
        JOIN cob_menus m ON m.id = p.menu_id
        WHERE p.grupo_id = ? AND m.codigo = ? AND p.ativo = 1
    """, (nivel, codigo_menu))
    return r is not None

def get_grupos() -> list:
    return local_query("SELECT * FROM cob_grupos ORDER BY id", ())

def get_todos_menus() -> list:
    return local_query("SELECT * FROM cob_menus ORDER BY secao, ordem", ())

def get_permissoes_grupo(grupo_id: int) -> list:
    """Retorna lista de codigos de menus liberados para o grupo."""
    rows = local_query("SELECT menu_id FROM cob_permissoes_menu WHERE grupo_id=? AND ativo=1", (grupo_id,))
    return [r["menu_id"] for r in rows]

def salvar_permissoes(grupo_id: int, menu_ids: list):
    """Salva permissões do grupo — desativa todos e reativa os selecionados."""
    local_execute("UPDATE cob_permissoes_menu SET ativo=0 WHERE grupo_id=?", (grupo_id,))
    for mid in menu_ids:
        local_execute("""
            INSERT INTO cob_permissoes_menu (grupo_id, menu_id, ativo)
            VALUES (?,?,1)
            ON CONFLICT(grupo_id, menu_id) DO UPDATE SET ativo=1
        """, (grupo_id, mid))

def nome_grupo(nivel: int) -> str:
    return GRUPO_NOMES.get(nivel, f'Nível {nivel}')
