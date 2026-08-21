"""
Corrige clientes com >60 dias sem OS — exclui entidades públicas/escolares
"""
import sys, os
sys.path.insert(0, '/opt/automacoes/jactos/cobranca')
os.chdir('/opt/automacoes/jactos/cobranca')

from app.core.db import query, query_one
from app.core.ixc_api import IXC_API_URL, _auth
import requests

EXCLUIR_KEYWORDS = ['ESCOLA', 'ESCOLAR', 'COLEGIO', 'COLÉGIO', 'CONSELHO', 'CAIXA ESCOLAR', 
                    'UNIDADE EXECUTORA', 'CENTRO DE EXCELENCIA', 'C. E.', 'C.E.']

def is_publica(razao):
    r = razao.upper()
    return any(k in r for k in EXCLUIR_KEYWORDS)

def log(msg): print(msg, flush=True)

def abrir_os(id_assunto, id_cliente, mensagem, setor):
    cli = query_one("SELECT cidade FROM ixcprovedor.cliente WHERE id=%s", (id_cliente,))
    id_cidade = str(cli["cidade"]) if cli and cli["cidade"] else ""
    url = f"{IXC_API_URL}/webservice/v1/su_oss_chamado"
    data = {
        "tipo": "C", "id_assunto": str(id_assunto), "id_cliente": str(id_cliente),
        "id_filial": "1", "setor": str(setor), "mensagem": mensagem,
        "status": "A", "prioridade": "B", "origem_cadastro": "P",
        "origem_endereco": "C", "id_cidade": id_cidade,
        "liberado": "1", "impresso": "N", "gera_comissao": "N",
        "melhor_horario_agenda": "Q", "status_pesquisa_satisfacao": "0",
    }
    try:
        r = requests.post(url, data=data, headers={"Authorization": _auth(), "ixcsoft": ""}, timeout=10)
        res = r.json()
        if res.get("type") == "success":
            return int(res.get("id", 0))
        log(f"  ERRO IXC: {res.get('message', res)}")
        return 0
    except Exception as e:
        log(f"  ERRO: {e}")
        return 0

clientes = query("""
    SELECT c.id, c.razao, MAX(DATEDIFF(CURDATE(), f.data_vencimento)) AS maior_atraso,
           SUM(f.valor_aberto) AS total_aberto
    FROM ixcprovedor.fn_areceber f
    INNER JOIN ixcprovedor.cliente c ON c.id = f.id_cliente
    INNER JOIN ixcprovedor.cliente_contrato cc ON cc.id = f.id_contrato
    WHERE f.status = 'A' AND f.data_vencimento < CURDATE()
      AND c.ativo = 'S' AND cc.status = 'A'
      AND DATEDIFF(CURDATE(), f.data_vencimento) >= 60
      AND c.id NOT IN (
        SELECT DISTINCT id_cliente FROM ixcprovedor.su_oss_chamado
        WHERE id_assunto IN (39, 246) AND status <> 'F'
      )
    GROUP BY c.id, c.razao
    ORDER BY maior_atraso DESC
""", ())

# Filtra públicas
clientes = [c for c in clientes if not is_publica(c["razao"] or "")]

os39  = [c for c in clientes if int(c["maior_atraso"] or 0) >= 90]
os246 = [c for c in clientes if 60 <= int(c["maior_atraso"] or 0) < 90]

log(f"\n{'='*60}")
log(f"PLANO DE AÇÃO — {len(clientes)} clientes (entidades públicas excluídas)")
log(f"{'='*60}")
log(f"\n🔴 Abre OS 39 (retirada direta) — {len(os39)} clientes:")
for c in os39:
    log(f"   #{c['id']} {c['razao']} — {c['maior_atraso']}d — R$ {float(c['total_aberto']):.2f}")
log(f"\n🟡 Abre OS 246 (entra no processo) — {len(os246)} clientes:")
for c in os246:
    log(f"   #{c['id']} {c['razao']} — {c['maior_atraso']}d — R$ {float(c['total_aberto']):.2f}")
log(f"\n{'='*60}")

confirma = input("Confirma execução? (s/n): ").strip().lower()
if confirma != 's':
    log("Cancelado.")
    sys.exit(0)

log("\nExecutando...")
ok39 = ok246 = erros = 0

for c in os39:
    msg = f"Retirada automática — {c['razao']} com {c['maior_atraso']}d inadimplente. Total: R$ {float(c['total_aberto']):.2f}"
    id_os = abrir_os(39, c["id"], msg, 8)
    if id_os:
        log(f"  ✅ OS 39 #{id_os} aberta — {c['razao']}")
        ok39 += 1
    else:
        erros += 1

for c in os246:
    msg = f"Cobrança automática — {c['razao']} com {c['maior_atraso']}d inadimplente. Total: R$ {float(c['total_aberto']):.2f}"
    id_os = abrir_os(246, c["id"], msg, 13)
    if id_os:
        log(f"  ✅ OS 246 #{id_os} aberta — {c['razao']}")
        ok246 += 1
    else:
        erros += 1

log(f"\n{'='*60}")
log(f"CONCLUÍDO — OS 39: {ok39} | OS 246: {ok246} | Erros: {erros}")
