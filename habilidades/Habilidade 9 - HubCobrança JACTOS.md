# Habilidade 9 — HubCobrança JACTOS / IaTechHub®

**Marco:** encerramento da grande fase visual + consolidação operacional + preparação da fase de automações/n8n.

**Projeto:** HubCobrança JACTOS, produto da IaTechHub®.

**Diretório de produção:** `/opt/automacoes/jactos/cobranca`

**Serviço:** `jactos_cobranca.service`

**Backend:** FastAPI/Uvicorn em `127.0.0.1:8019`.

## 1. Finalidade

Documento de continuidade para qualquer novo agente que retome o HubCobrança JACTOS em outro chat. Consolida o que foi efetivamente feito nesta fase e estabelece as regras para a próxima fase: **auditoria completa das automações existentes e estudo da adoção do n8n como orquestrador**.

Esta habilidade não autoriza automaticamente novas alterações.

## 2. Estado validado desta fase

Módulos visualmente revisados e aceitos: Visão Geral, Fila de Cobrança, Primeira Cobrança, Segunda Cobrança, Nunca Pagaram, Colocar no Serasa, Clientes no Serasa, Saídas do Serasa, Promessas Quebradas, Promessas Realizadas, Pagos, Cancelamentos, Resultado Nunca Pagaram, Gerencial, Desempenho, Equipe, Desempenho Equipe, Sessões, Cancelamentos por Inadimplência e Equipamentos Cancelados.

**Decisão explícita:** a fase de layout está encerrada. Não fazer novas alterações visuais, cosméticas ou de layout sem solicitação expressa.

## 3. Identidade visual

Marca oficial: **IaTechHub®**.

Produto: **IaTechHub® · Hub Cobrança**.

Rodapé padrão: `IaTechHub® · Hub Cobrança`.

Manter o padrão visual já validado.

## 4. Filial — regra de negócio obrigatória

Cada usuário possui uma filial padrão em `cob_usuarios.filial_id`, usada como filial inicial no login.

Usuários de nível **3 ou superior podem trocar a filial ativa** quando necessário para apoiar outras filiais. Essa troca é funcionalidade legítima de negócio e não deve ser removida nem tratada como vulnerabilidade.

Não criar `cob_usuario_filiais` por suposição. Não remover o seletor. Não transformar a filial cadastrada no usuário em limite absoluto.

Distinção obrigatória:

- `ixcprovedor.fn_areceber.filial_id` = filial financeira da fatura;
- `ixcprovedor.cliente_contrato.id_filial` = filial contratual.

Não assumir equivalência, não usar fallback arbitrário e não substituir um pelo outro. Para OS baseada em contrato, respeitar a resolução por `cliente_contrato.id_filial` já estabelecida no projeto.

## 5. Regras funcionais consolidadas

### Serasa

A negativação não é automática. **Negativar cliente** prepara/preserva a OS 63 e registra interação, mantendo processo manual. Não introduzir API de negativação sem requisito explícito. Não duplicar OS 63.

### Horário

Novas interações usam `America/Sao_Paulo`. Não corrigir histórico antigo sem requisito.

### Idempotência

Execução repetida não pode produzir, sem intenção, duas OS, duas interações, dois alertas, dois efeitos financeiros ou duplicidade de registros.

### Financeiro

Não substituir valor real do IXC por valor estimado ou hardcoded quando houver dado real.

### ClickDF

Não importar regras comerciais do ClickDF para o JACTOS. Dependências históricas devem ser saneadas em etapa própria.

## 6. Segurança — decisão desta fase

Foi realizada auditoria de autenticação, sessão, permissões, filial, CORS, headers, secrets, banco e systemd. Foram identificadas oportunidades de hardening, incluindo revisão de credenciais, permissões de SQLite, execução do serviço como root, headers de segurança, registro público e autorização por recurso.

**Decisão desta fase:** segurança pode ficar em espera. Não transformar esses achados em alterações agora, salvo solicitação específica.

Nunca expor credenciais, tokens ou secrets em documentação, logs, commits ou mensagens.

## 7. Inventário de automações identificado

Scripts/rotinas relevantes:

1. `cron_correcao_cancelamentos.py` — correção de datas de cancelamento;
2. `cron_bloqueio_antecipado.py` — bloqueio antecipado;
3. `cron_alerta_fatura_nao_liberada.py` — fatura não liberada;
4. `cron_monitoramento.py` — monitoramento operacional;
5. `cron_promessas.py` — promessas;
6. `cron_parcela_errada.py` — auditoria de parcelas;
7. `cron_resumo_acessos.py` — acessos/equipe;
8. `cron_auditoria.py` — auditoria geral;
9. `cron_alerta_serasa_aprovado.py` — Serasa;
10. `cron_churn.py` — churn;
11. `cron_previsao_receita.py` — previsão de receita;
12. `cron_retencao.py` — retenção;
13. `cron_qualidade_vendas.py` — qualidade de vendas;
14. `cron_resolver_pagas.py` — resolução de interações/promessas após pagamento;
15. `cron_limpeza_interacoes.py` — limpeza/manutenção;
16. `cron_auditoria_retiradas.py` — auditoria de retiradas;
17. `cron_telegram.py` — relatórios/alertas Telegram;
18. `cron_alerta_inadimplente.py` — alertas de inadimplência.

Também existe `corrigir_os_pendentes.py`, que precisa ser classificado antes de qualquer decisão sobre agendamento.

Arquivos `.bak` e `.pre_*` não são automaticamente ativos.

## 8. Frequências documentadas

Incluem: resolver pagas a cada 10 min; limpeza a cada hora; correção de cancelamentos 03h; bloqueio antecipado 06h; fatura não liberada 07h em dias definidos; monitoramento/promessas 08h; auditoria geral a cada 2h; parcela errada em múltiplos horários; resumo/acessos 18h; churn mensal; previsão de receita semanal; retenção semanal; Telegram/relatórios em horários programados; qualidade de vendas programada; inadimplência horária; auditoria de retiradas várias vezes em horário comercial; cache Serasa periódico.

**Regra:** script existente não significa cron atualmente ativo. Antes de migrar qualquer rotina para n8n, confrontar arquivo, crontab, systemd, processos, logs e última execução real.

## 9. Telegram

Telegram já é parte importante da operação: cobrança, inadimplência, Serasa, retenção, auditoria, retiradas, qualidade, promessas, acessos, relatórios, bloqueio antecipado, fatura não liberada e parcelas.

Existem destinos de grupo e rotas privadas de gestão.

**Nunca documentar tokens ou IDs sensíveis.** Manter em ambiente/configuração segura.

## 10. Pontos fortes das automações atuais

### Auditoria de retiradas

É uma das rotinas mais ricas: analisa OS 38, OS 34, OS 190, movimentação de produtos, `status_comodato`, anexos, técnicos e retiradas agendadas, podendo abrir OS automaticamente em situações definidas.

### Auditoria geral

Monitora inconsistências e possui alerta de falha de autenticação/API do IXC.

### Resolver pagas

Forte candidata a operação silenciosa com resumo de recuperação quando houver resultado relevante.

### Bloqueio antecipado

Possui tabela local e proteção contra duplicidade.

### Inadimplência

Possui tabela local para evitar repetição de alertas.

### Qualidade de vendas

Possui regra de alerta por inadimplência de vendedores com critérios mínimos.

### Retenção

Possui score/classificação já documentados. Não alterar pesos sem autorização.

## 11. Dependências ClickDF

Algumas automações ainda referenciam base/componente comercial do ClickDF, especialmente `cron_churn.py` e `cron_auditoria_retiradas.py`.

Isso não significa que estejam erradas. Antes de remover/substituir: identificar dado usado, confirmar necessidade, localizar equivalente JACTOS/IXC, validar e só então planejar saneamento.

## 12. Nova arquitetura em avaliação — n8n

A ideia aprovada para estudo é:

> **n8n como orquestrador das automações do HubCobrança.**

Não significa colocar necessariamente toda a lógica Python dentro do n8n.

Arquitetura preferencial:

```text
n8n = ORQUESTRAÇÃO
Python = MOTOR ESPECIALIZADO
HubCobrança/IXC = SISTEMA E DADOS
Telegram = DISTRIBUIÇÃO/ALERTA
```

Fluxo:

```text
n8n → trigger/agendamento → robô Python → resultado estruturado → severidade → deduplicação/cooldown → Telegram → registro
```

Benefícios esperados: centralização de agendamentos, retries, timeout, histórico, Telegram, escalonamento, monitoramento de falhas e combinação de resultados.

## 13. Não migrar tudo de uma vez

Primeiro padronizar resultados dos robôs. Exemplo:

```json
{
  "automacao": "auditoria_retiradas",
  "status": "OK",
  "processados": 27,
  "alertas": 2,
  "criticos": 1,
  "duracao": 12.4
}
```

Depois testar um piloto de baixo risco, mantendo o cron antigo como contingência. Só depois migrar gradualmente.

## 14. Central de Alertas futura

Modelo:

```text
AUTOMAÇÃO → EVENTO/RESULTADO → SEVERIDADE → DEDUPLICAÇÃO/COOLDOWN → ROTEAMENTO
                                                     ├─ silêncio
                                                     ├─ grupo cobrança
                                                     ├─ privado gestão
                                                     └─ grupo + privado
```

Classificação sugerida:

- 🟢 normal: registrar;
- 🟡 atenção: grupo;
- 🟠 importante: grupo + gestão;
- 🔴 crítico: gestão imediata.

É proposta arquitetural, não implementação autorizada.

## 15. Novas automações candidatas

- Automation Health Check: detectar robô que não executou, atrasou ou falhou;
- Detector de anomalias: hoje × ontem × média de 7 dias;
- Cliente crítico: dívida + atraso + promessas quebradas + tentativas;
- SLA de OS parada;
- resumo de recuperação financeira;
- pico de cancelamentos;
- saúde do Telegram;
- risco de equipamento;
- anomalia Serasa;
- deterioração de desempenho da equipe.

## 16. Próxima fase — ordem obrigatória

### A. Inventário real

Para cada robô mapear arquivo, função, frequência real, fonte, dependências, efeitos colaterais, tabelas, APIs, Telegram, logs, criticidade, idempotência e última execução.

### B. Classificação

Classificar: manter, melhorar, centralizar Telegram, silenciosa, migrar agendamento para n8n, refatorar depois, substituir ou criar nova.

### C. Piloto

Migrar somente uma rotina de baixo risco e manter contingência.

### D. Migração gradual

Uma automação por vez, com comparação do resultado antigo × n8n.

### E. Central de Alertas

Somente depois de estabilizar execução: severidade, deduplicação, cooldown e roteamento.

## 17. Regras específicas para n8n

Não desligar cron existente sem validação.

Não migrar automação crítica em lote.

Não duplicar execução.

Não criar dois agendadores para o mesmo robô sem intenção.

Não mover lógica financeira para workflow sem necessidade.

Não colocar credenciais diretamente em nós quando houver mecanismo seguro de credenciais.

Não apagar Python porque n8n consegue executar comandos.

Não tratar n8n como substituto automático do HubCobrança.

Preferir n8n para orquestração, Python para regras complexas já testadas, respostas estruturadas, idempotência, logs, retries, timeout e observabilidade.

## 18. Backup e continuidade

Foi criado backup antes desta documentação. Referência:

`/opt/automacoes/jactos/HUB_COBRANCA_BACKUP_PRE_HABILIDADE9_20260908_023556.tar.gz`

Backups e arquivos `.pre_*` não devem entrar no Git.

## 19. Checklist do novo agente

- ler Habilidade 9;
- ler este Prompt Mestre;
- verificar `git status`, branch e commit;
- verificar serviço e backup;
- entender regras de filial;
- não mexer em layout sem autorização;
- não assumir script = cron;
- mapear automações antes de n8n;
- não desligar cron antes de validar substituição;
- não expor credenciais;
- não importar ClickDF;
- preservar idempotência;
- testar antes de afirmar.

## 20. Em caso de dúvida

Classificar como: documentado, confirmado no código, confirmado no banco, inferido ou desconhecido.

Se houver risco de perda de dados, cobrança, financeiro, filial, permissão, duplicidade, Serasa, OS ou cancelamento: **parar e validar**.

## 21. Regra final

Preserve o que funciona.

Investigue antes de alterar.

Não invente regras.

Não altere layout sem autorização.

Não faça negativação automática.

Não use dados fictícios quando houver dados reais.

Não faça alteração destrutiva sem validação.

Não migre automações para n8n em lote.

Não desligue cron antigo antes de validar o novo fluxo.

Não faça commit/push sem autorização.

Não exponha credenciais.

**Objetivo:** evoluir o HubCobrança com segurança, observabilidade, automação e continuidade.
