from datetime import datetime
from app.core.db import query
from app.core.db_local import db_local


def sincronizar():
    inicio = datetime.now()

    clientes = query("""
        SELECT
            os.id AS os63,
            os.id_cliente,
            os.id_contrato_kit AS id_contrato,
            os.data_abertura,
            os.status AS status_os,
            os.mensagem,
            c.razao,
            c.cnpj_cpf,
            cc.status AS status_contrato,
            cc.data_cancelamento,
            cc.motivo_cancelamento,
            cc.motivo_adicional,
            cc.motivo_desistencia,
            cc.origem_cancelamento,
            cc.id_filial
        FROM ixcprovedor.su_oss_chamado os
        INNER JOIN ixcprovedor.cliente c
                ON c.id = os.id_cliente
        LEFT JOIN ixcprovedor.cliente_contrato cc
               ON cc.id = os.id_contrato_kit
        WHERE os.id_assunto = 63
          AND os.status NOT IN ('F', 'AN')
          AND os.id = (
              SELECT MAX(os2.id)
              FROM ixcprovedor.su_oss_chamado os2
              WHERE os2.id_cliente = os.id_cliente
                AND os2.id_assunto = 63
                AND os2.status NOT IN ('F', 'AN')
          )
          AND NOT EXISTS (
              SELECT 1
              FROM ixcprovedor.negativacao_spc_serasa n
              WHERE n.id_cliente = os.id_cliente
                AND n.status = 1
          )
        ORDER BY os.data_abertura DESC, os.id DESC
    """)

    if not clientes:
        with db_local() as conn:
            conn.execute("DELETE FROM cob_serasa_colocar")
            conn.execute("DELETE FROM cob_serasa_colocar_equipamentos")
            conn.commit()
        print("CACHE SERASA: fila vazia.")
        return

    ids_clientes = [int(r["id_cliente"]) for r in clientes]
    ids_contratos = [
        int(r["id_contrato"])
        for r in clientes
        if r.get("id_contrato")
    ]

    financeiro = {}
    equipamentos = {}

    if ids_contratos:
        placeholders = ",".join(["%s"] * len(ids_contratos))

        rows_fin = query(f"""
            SELECT
                id_contrato,
                SUM(
                    CASE
                        WHEN valor_aberto > 0
                        THEN valor_aberto
                        ELSE 0
                    END
                ) AS valor_financeiro
            FROM ixcprovedor.fn_areceber
            WHERE id_contrato IN ({placeholders})
              AND status = 'A'
              AND valor_aberto > 0
              AND data_vencimento < CURDATE()
            GROUP BY id_contrato
        """, tuple(ids_contratos))

        for r in rows_fin:
            financeiro[int(r["id_contrato"])] = float(
                r.get("valor_financeiro") or 0
            )

        rows_eq = query(f"""
            SELECT
                pm.id_contrato,
                pm.id_patrimonio,
                pm.cliente_destino,
                pm.data_movimentacao,
                pat.id_almoxarifado,
                pat.descricao,
                pat.serial,
                pat.id_mac,
                pat.valor_bem
            FROM ixcprovedor.patrimonio_movimentacao pm
            INNER JOIN ixcprovedor.patrimonio pat
                    ON pat.id = pm.id_patrimonio
            INNER JOIN (
                SELECT
                    pm2.id_patrimonio,
                    MAX(pm2.id) AS ultima_id
                FROM ixcprovedor.patrimonio_movimentacao pm2
                WHERE pm2.id_contrato IN ({placeholders})
                  AND pm2.id_patrimonio IS NOT NULL
                  AND pm2.id_patrimonio > 0
                GROUP BY pm2.id_patrimonio
            ) ult
                    ON ult.id_patrimonio = pm.id_patrimonio
                   AND ult.ultima_id = pm.id
        """, tuple(ids_contratos))

        clientes_por_contrato = {
            int(r["id_contrato"]): int(r["id_cliente"])
            for r in clientes
            if r.get("id_contrato")
        }

        for r in rows_eq:
            contrato = int(r["id_contrato"])
            cliente = clientes_por_contrato.get(contrato)

            if not cliente:
                continue

            almox = int(r.get("id_almoxarifado") or 0)
            cliente_destino = int(r.get("cliente_destino") or 0)

            if cliente_destino > 0:
                if cliente_destino != cliente:
                    status = "novo_cliente"
                    status_label = "Vinculado a outro cliente"
                    pendente = 0
                else:
                    status = "comodato"
                    status_label = "Em comodato / com cliente"
                    pendente = 1
            elif almox == 29:
                status = "perdido"
                status_label = "Perdido"
                pendente = 1
            elif almox == 16:
                status = "avaria"
                status_label = "Avaria"
                pendente = 1
            elif almox > 0:
                status = "estoque"
                status_label = "No estoque"
                pendente = 0
            else:
                status = "indefinido"
                status_label = "Indefinido"
                pendente = 0

            equipamentos.setdefault(contrato, []).append({
                "id_cliente": cliente,
                "id_contrato": contrato,
                "id_patrimonio": r.get("id_patrimonio"),
                "equipamento": r.get("descricao") or "",
                "valor": float(r.get("valor_bem") or 0),
                "serial": r.get("serial") or "",
                "mac": r.get("id_mac") or "",
                "status": status,
                "status_label": status_label,
                "pendente": pendente,
                "data_movimentacao": (
                    r["data_movimentacao"].isoformat()
                    if r.get("data_movimentacao")
                    else None
                ),
            })

    agora = datetime.now().isoformat(sep=" ", timespec="seconds")

    with db_local() as conn:
        conn.execute("DELETE FROM cob_serasa_colocar")
        conn.execute("DELETE FROM cob_serasa_colocar_equipamentos")

        for r in clientes:
            cliente = int(r["id_cliente"])
            contrato = (
                int(r["id_contrato"])
                if r.get("id_contrato")
                else None
            )

            valor_fin = financeiro.get(contrato, 0) if contrato else 0
            lista_eq = equipamentos.get(contrato, []) if contrato else []

            valor_eq = sum(float(e["valor"] or 0) for e in lista_eq)

            if valor_fin > 0 and valor_eq > 0:
                categoria = "ambos"
            elif valor_fin > 0:
                categoria = "financeiro"
            elif valor_eq > 0:
                categoria = "equipamento"
            else:
                categoria = "sem_valor"

            conn.execute("""
                INSERT INTO cob_serasa_colocar (
                    id_cliente,
                    id_contrato,
                    os63,
                    razao,
                    cnpj_cpf,
                    data_abertura,
                    status_os,
                    mensagem,
                    status_contrato,
                    data_cancelamento,
                    motivo_cancelamento,
                    motivo_adicional,
                    motivo_desistencia,
                    origem_cancelamento,
                    id_filial,
                    valor_financeiro,
                    valor_equipamento,
                    quantidade_equipamentos,
                    categoria,
                    atualizado_em
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                cliente,
                contrato,
                int(r["os63"]),
                r.get("razao"),
                r.get("cnpj_cpf"),
                str(r["data_abertura"]) if r.get("data_abertura") else None,
                r.get("status_os"),
                r.get("mensagem"),
                r.get("status_contrato"),
                str(r["data_cancelamento"]) if r.get("data_cancelamento") else None,
                r.get("motivo_cancelamento"),
                r.get("motivo_adicional"),
                r.get("motivo_desistencia"),
                r.get("origem_cancelamento"),
                r.get("id_filial"),
                valor_fin,
                valor_eq,
                len(lista_eq),
                categoria,
                agora,
            ))

            for e in lista_eq:
                conn.execute("""
                    INSERT INTO cob_serasa_colocar_equipamentos (
                        id_cliente,
                        id_contrato,
                        id_patrimonio,
                        equipamento,
                        valor,
                        serial,
                        mac,
                        status,
                        status_label,
                        pendente,
                        data_movimentacao,
                        atualizado_em
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    cliente,
                    contrato,
                    e["id_patrimonio"],
                    e["equipamento"],
                    e["valor"],
                    e["serial"],
                    e["mac"],
                    e["status"],
                    e["status_label"],
                    e["pendente"],
                    e["data_movimentacao"],
                    agora,
                ))

        conn.commit()

    tempo = (datetime.now() - inicio).total_seconds()

    print(
        f"CACHE SERASA OK | clientes={len(clientes)} | "
        f"equipamentos={sum(len(v) for v in equipamentos.values())} | "
        f"tempo={tempo:.3f}s"
    )


if __name__ == "__main__":
    sincronizar()
