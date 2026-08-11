from app.core.db import query, query_one

ALMOX_PERDIDO  = 29
ALMOX_AVARIA   = 16
ALMOX_RETIRADAS = 30

def get_equipamentos_cancelados(meses=6, mes_filtro=None):
    from datetime import datetime
    
    # 1. Busca contratos cancelados
    filtro_mes = ""
    params_cc = [meses]
    if mes_filtro:
        try:
            m, a = mes_filtro.split('-')
            filtro_mes = f"AND DATE_FORMAT(cc.data_cancelamento,'%%Y-%%m') = '{a}-{m}'"
        except: pass

    contratos = query(f"""
        SELECT cc.id AS contrato_id, cc.id_cliente, c.razao AS cliente,
               COALESCE(c.whatsapp, c.telefone_celular, c.fone,'') AS telefone,
               cc.data_cancelamento,
               DATE_FORMAT(cc.data_cancelamento,'%%m/%%Y') AS mes_cancel
        FROM ixcprovedor.cliente_contrato cc
        INNER JOIN ixcprovedor.cliente c ON c.id=cc.id_cliente
        WHERE cc.status='I'
          AND cc.data_cancelamento >= DATE_SUB(CURDATE(), INTERVAL %s MONTH)
          {filtro_mes}
        ORDER BY cc.data_cancelamento DESC
        LIMIT 500
    """, tuple(params_cc))

    if not contratos:
        return []

    contrato_ids = tuple(c["contrato_id"] for c in contratos)
    cliente_ids  = tuple(c["id_cliente"] for c in contratos)

    # 2. Busca última OS de retirada por cliente
    ph_cli = ",".join(["%s"]*len(cliente_ids))
    os_rows = query(f"""
        SELECT id_cliente, MAX(id) AS os_id
        FROM ixcprovedor.su_oss_chamado
        WHERE id_assunto IN (22,39) AND id_cliente IN ({ph_cli})
        GROUP BY id_cliente
    """, tuple(cliente_ids))
    os_map_id = {r["id_cliente"]: r["os_id"] for r in os_rows}

    # Busca detalhes das OS
    os_ids = tuple(os_map_id.values())
    os_details = {}
    if os_ids:
        ph_os = ",".join(["%s"]*len(os_ids))
        for o in query(f"SELECT id, id_assunto, status FROM ixcprovedor.su_oss_chamado WHERE id IN ({ph_os})", tuple(os_ids)):
            os_details[o["id"]] = o

    # 3. Busca última movimentação de patrimônio por contrato+patrimônio
    ph_con = ",".join(["%s"]*len(contrato_ids))
    # Busca cliente atual em comodato
    ph_con2 = ",".join(["%s"]*len(contrato_ids))
    comodatos = query(f"""
        SELECT pm.id_patrimonio, pm.cliente_destino, pm.id_contrato AS contrato_destino,
               c.razao AS cliente_comodato
        FROM ixcprovedor.patrimonio_movimentacao pm
        INNER JOIN ixcprovedor.cliente c ON c.id=pm.cliente_destino
        INNER JOIN ixcprovedor.cliente_contrato cc ON cc.id=pm.id_contrato AND cc.status='A'
        WHERE pm.id_contrato IN ({ph_con2})
          AND pm.cliente_destino > 0
          AND pm.id = (
            SELECT MAX(id) FROM ixcprovedor.patrimonio_movimentacao pm2
            WHERE pm2.id_patrimonio=pm.id_patrimonio AND pm2.cliente_destino > 0
          )
    """, tuple(contrato_ids))
    comodato_map = {r["id_patrimonio"]: dict(r) for r in comodatos}

    # Busca todos os patrimônios do contrato com situação ATUAL da tabela patrimônio
    movs = query(f"""
        SELECT pm.id_contrato, pm.id_patrimonio,
               pm.cliente_destino,
               pm.data_movimentacao,
               pat.descricao AS equipamento, pat.serial, pat.id_mac, pat.valor_bem,
               pat.id_almoxarifado AS equip_almox_atual,
               alm.descricao AS almox_nome
        FROM ixcprovedor.patrimonio_movimentacao pm
        INNER JOIN ixcprovedor.patrimonio pat ON pat.id=pm.id_patrimonio
        INNER JOIN ixcprovedor.cliente_contrato cc ON cc.id=pm.id_contrato AND cc.status='I'
        LEFT JOIN ixcprovedor.almox alm ON alm.id=pat.id_almoxarifado
        WHERE pm.id_contrato IN ({ph_con})
        ORDER BY pm.id_contrato, pm.id_patrimonio, pm.data_movimentacao DESC
    """, tuple(contrato_ids))

    # Pega última movimentação por patrimônio+contrato
    mov_map = {}
    for m in movs:
        key = (m["id_contrato"], m["id_patrimonio"])
        if key not in mov_map:
            mov_map[key] = dict(m)
            mov_map[key]["id_almoxarifado_destino"] = m["equip_almox_atual"]

    # 4. Monta resultado
    contrato_map = {c["contrato_id"]: dict(c) for c in contratos}
    result = []
    for (contrato_id, pat_id), mov in mov_map.items():
        cc = contrato_map.get(contrato_id, {})
        id_cliente = cc.get("id_cliente")
        os_id = os_map_id.get(id_cliente)
        os_det = os_details.get(os_id, {}) if os_id else {}

        almox  = int(mov.get("id_almoxarifado_destino") or 0)
        cli_dest = int(mov.get("cliente_destino") or 0)

        if almox == ALMOX_PERDIDO:
            status_equip = "perdido"; status_label = "❌ Perdido"
        elif almox == ALMOX_AVARIA:
            status_equip = "avaria"; status_label = "🔧 Avaria"
        elif almox > 0:
            status_equip = "estoque"; status_label = "✅ No estoque"
        elif cli_dest > 0 and cli_dest != id_cliente:
            status_equip = "novo_cliente"; status_label = "🔄 Novo cliente"
        elif cli_dest > 0:
            status_equip = "nao_recuperado"; status_label = "❌ Não recuperado"
        else:
            status_equip = "indefinido"; status_label = "⚠️ Indefinido"

        comodato = comodato_map.get(int(mov.get("id_patrimonio") or 0), {})
        row = {**cc, **mov,
               "os_id": os_id, "os_status": os_det.get("status"), "os_assunto": os_det.get("id_assunto"),
               "status_equip": status_equip, "status_label": status_label,
               "cliente_comodato": comodato.get("cliente_comodato"),
               "contrato_comodato": comodato.get("contrato_destino")}
        result.append(row)

    # Contratos sem patrimônio
    contratos_com_mov = {k[0] for k in mov_map.keys()}
    for cc in contratos:
        if cc["contrato_id"] not in contratos_com_mov:
            id_cliente = cc["id_cliente"]
            os_id = os_map_id.get(id_cliente)
            os_det = os_details.get(os_id, {}) if os_id else {}
            result.append({**dict(cc),
                "id_patrimonio": None, "equipamento": None, "serial": None,
                "id_mac": None, "valor_bem": None, "almox_nome": None,
                "cliente_destino": None, "id_almoxarifado_destino": None,
                "os_id": os_id, "os_status": os_det.get("status"),
                "status_equip": "sem_patrimonio", "status_label": "⚠️ Sem registro"})

    result.sort(key=lambda r: str(r.get("data_cancelamento") or ""), reverse=True)
    return result

def alertar_equipamentos_criticos():
    """Envia alerta Telegram com equipamentos perdidos ou sem OS de retirada."""
    import requests
    from datetime import datetime, timezone, timedelta
    TOKEN = "8027006096:AAHiJEdtFyPresI81tWgs-Je2PKdaYAyWtY"
    CHATS = ["2135602169", "2135602169"]
    agora = datetime.now(timezone(timedelta(hours=-3)))

    rows = get_equipamentos_cancelados(meses=3)

    perdidos = [r for r in rows if r.get("status_equip") == "perdido" and r.get("id_patrimonio")]
    sem_os   = [r for r in rows if not r.get("os_id") and r.get("id_patrimonio")]

    if not perdidos and not sem_os:
        return

    linhas = [f"📦 <b>ALERTA — EQUIPAMENTOS CANCELADOS</b>", f"📅 {agora.strftime('%d/%m/%Y %H:%M')}", ""]

    if perdidos:
        linhas.append(f"❌ <b>Equipamentos PERDIDOS ({len(perdidos)}):</b>")
        for r in perdidos[:5]:
            val = f"R$ {float(r['valor_bem']):.2f}" if r.get("valor_bem") else "—"
            linhas.append(f"  • {r['cliente'][:30]} — {r.get('equipamento','')[:25]} ({val})")
        linhas.append("")

    if sem_os:
        linhas.append(f"⚠️ <b>Sem OS de retirada ({len(sem_os)}):</b>")
        for r in sem_os[:5]:
            linhas.append(f"  • {r['cliente'][:30]} — {r.get('equipamento','')[:25]}")
        linhas.append("")

    msg = "\n".join(linhas)
    for chat in CHATS:
        try:
            requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                data={"chat_id": chat, "text": msg, "parse_mode": "HTML"}, timeout=10)
        except: pass

def get_kpis_equipamentos(meses=6):
    rows = get_equipamentos_cancelados(meses=meses)
    clientes = set(r["id_cliente"] for r in rows)
    total_cancelamentos = len(clientes)
    equip = [r for r in rows if r.get("id_patrimonio")]
    total_equip    = len(equip)
    recuperados    = sum(1 for r in equip if r["status_equip"] == "estoque")
    nao_recuperado = sum(1 for r in equip if r["status_equip"] in ("nao_recuperado","indefinido"))
    perdidos       = sum(1 for r in equip if r["status_equip"] == "perdido")
    avarias        = sum(1 for r in equip if r["status_equip"] == "avaria")
    novo_cliente   = sum(1 for r in equip if r["status_equip"] == "novo_cliente")
    sem_os         = sum(1 for r in rows if not r.get("os_id") and r.get("id_patrimonio"))
    valor_risco    = sum(float(r.get("valor_bem") or 0) for r in equip if r["status_equip"] in ("nao_recuperado","perdido","indefinido"))
    valor_recuperado = sum(float(r.get("valor_bem") or 0) for r in equip if r["status_equip"] == "estoque")

    meses_map = {}
    for r in rows:
        mes = r.get("mes_cancel","?")
        if mes not in meses_map:
            meses_map[mes] = {"mes": mes, "data_cancel": r.get("data_cancelamento"),
                "cancelamentos": set(), "equip_total":0, "recuperados":0,
                "nao_recuperados":0, "perdidos":0, "avarias":0, "sem_os":0}
        meses_map[mes]["cancelamentos"].add(r["id_cliente"])
        if r.get("id_patrimonio"):
            meses_map[mes]["equip_total"] += 1
            s = r["status_equip"]
            if s=="estoque": meses_map[mes]["recuperados"] += 1
            elif s in ("nao_recuperado","indefinido"): meses_map[mes]["nao_recuperados"] += 1
            elif s=="perdido": meses_map[mes]["perdidos"] += 1
            elif s=="avaria": meses_map[mes]["avarias"] += 1
        if not r.get("os_id") and r.get("id_patrimonio"):
            meses_map[mes]["sem_os"] += 1

    timeline = sorted(meses_map.values(), key=lambda x: str(x["data_cancel"] or ""), reverse=True)
    for t in timeline:
        t["cancelamentos"] = len(t["cancelamentos"])

    return {"total_cancelamentos": total_cancelamentos, "total_equip": total_equip,
            "recuperados": recuperados, "nao_recuperado": nao_recuperado,
            "perdidos": perdidos, "avarias": avarias, "novo_cliente": novo_cliente,
            "sem_os": sem_os, "valor_risco": valor_risco, "valor_recuperado": valor_recuperado,
            "taxa_recuperacao": round(recuperados/total_equip*100,1) if total_equip else 0,
            "timeline": timeline}
