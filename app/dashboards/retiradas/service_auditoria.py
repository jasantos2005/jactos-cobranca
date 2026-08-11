from app.core.db import query, query_one

# IDs da tabela funcionarios — atualizado 08/08/2026
# ALEXANDRE=13, DENILSON=54, EDERSON LEITE=72, JAIRO=18, JOSE MARCONDES=19
# JOSEILTON=38, LEANDRO=47, ODAIR=12, RICHARDSON=67, RICARDO-ILHA=50
# RODRIGO SANTOS=35, ROGERIO=56, VICTOR FERREIRA=55, WELINTON=60
# WELLINGTON PIAÇABUÇU=46
TECNICOS_IDS = (13, 54, 72, 18, 19, 38, 47, 12, 67, 50, 35, 56, 55, 60, 46)

def get_ranking_tecnicos(data_ini=None, data_fim=None):
    ph = ",".join(["%s"]*len(TECNICOS_IDS))
    filtro = ""
    params = list(TECNICOS_IDS)
    if data_ini:
        filtro += " AND DATE(o.data_fechamento) >= %s"
        params.append(data_ini)
    if data_fim:
        filtro += " AND DATE(o.data_fechamento) <= %s"
        params.append(data_fim)
    return query(f"""
        SELECT f.funcionario AS tecnico, f.id AS id_tecnico,
               COUNT(DISTINCT o.id) AS total_retiradas,
               SUM(CASE WHEN a.id IS NOT NULL THEN 1 ELSE 0 END) AS com_foto,
               SUM(CASE WHEN a.id IS NULL THEN 1 ELSE 0 END) AS sem_foto
        FROM ixcprovedor.su_oss_chamado o
        INNER JOIN ixcprovedor.funcionarios f ON f.id=o.id_tecnico
        LEFT JOIN ixcprovedor.su_oss_chamado_arquivos a ON a.id_oss_chamado=o.id AND a.nome_arquivo NOT LIKE '%%.pdf' AND a.descricao NOT LIKE '%%Assinatura%%' AND a.descricao NOT LIKE '%%Ordem%%'
        WHERE o.id_assunto=39 AND o.status='F'
          AND o.id_tecnico IN ({ph})
          AND o.mensagem NOT LIKE 'Retirada automática%%' {filtro}
        GROUP BY f.id, f.funcionario
        ORDER BY total_retiradas DESC
    """, tuple(params))

def get_os_pendentes_auditoria():
    """OS 39 finalizadas hoje sem foto ou sem técnico válido."""
    ph = ",".join(["%s"]*len(TECNICOS_IDS))
    return query(f"""
        SELECT o.id AS os_id, c.id AS id_cliente, c.razao,
               DATE_FORMAT(o.data_fechamento,'%%d/%%m/%%Y %%H:%%i') AS data_fechamento,
               f.funcionario AS tecnico,
               COUNT(a.id) AS qtd_fotos,
               CASE
                 WHEN o.id_tecnico IS NULL OR o.id_tecnico=0 OR o.id_tecnico NOT IN ({ph}) THEN 'sem_tecnico'
                 WHEN COUNT(a.id)=0 THEN 'sem_foto'
                 ELSE 'ok'
               END AS status_auditoria
        FROM ixcprovedor.su_oss_chamado o
        INNER JOIN ixcprovedor.cliente c ON c.id=o.id_cliente
        LEFT JOIN ixcprovedor.funcionarios f ON f.id=o.id_tecnico
        LEFT JOIN ixcprovedor.su_oss_chamado_arquivos a ON a.id_oss_chamado=o.id AND a.nome_arquivo NOT LIKE '%%.pdf' AND a.descricao NOT LIKE '%%Assinatura%%' AND a.descricao NOT LIKE '%%Ordem%%'
        WHERE o.id_assunto=39 AND o.status='F'
          AND DATE(o.data_fechamento) >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
          AND o.mensagem NOT LIKE 'Retirada automática%%'
          AND (o.id_tecnico IN ({ph}) OR o.id_tecnico IS NULL OR o.id_tecnico=0)
        GROUP BY o.id, c.id, c.razao, o.data_fechamento, f.funcionario, o.id_tecnico
        ORDER BY o.data_fechamento DESC
        LIMIT 100
    """, TECNICOS_IDS + TECNICOS_IDS)

def get_kpis_auditoria():
    ph = ",".join(["%s"]*len(TECNICOS_IDS))
    # Busca OS dos últimos 7 dias
    os_list = query(f"""
        SELECT o.id, o.id_tecnico,
               COUNT(a.id) AS qtd_fotos
        FROM ixcprovedor.su_oss_chamado o
        LEFT JOIN ixcprovedor.su_oss_chamado_arquivos a ON a.id_oss_chamado=o.id AND (a.nome_arquivo LIKE '%%.jpg' OR a.nome_arquivo LIKE '%%.jpeg' OR a.nome_arquivo LIKE '%%.png' OR a.nome_arquivo LIKE '%%.gif' OR a.nome_arquivo LIKE '%%.webp') AND a.nome_arquivo != '/' AND a.nome_arquivo != '' AND a.descricao NOT LIKE '%%Assinatura%%'
        WHERE o.id_assunto=39 AND o.status='F'
          AND DATE(o.data_fechamento) >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
          AND o.mensagem NOT LIKE 'Retirada automática%%'
        GROUP BY o.id, o.id_tecnico
    """, ())
    total = len(os_list)
    validas = sum(1 for o in os_list if o["id_tecnico"] in TECNICOS_IDS and int(o["qtd_fotos"] or 0) > 0)
    sem_foto = sum(1 for o in os_list if int(o["qtd_fotos"] or 0) == 0)
    sem_tecnico = sum(1 for o in os_list if not o["id_tecnico"] or o["id_tecnico"] not in TECNICOS_IDS)
    return {"total_7d": total, "validas": validas, "sem_foto": sem_foto, "sem_tecnico": sem_tecnico}
