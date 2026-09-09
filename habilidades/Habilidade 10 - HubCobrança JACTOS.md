# Habilidade 10 — HubCobrança JACTOS

## 1. OBJETIVO DO PROJETO

Transformar o n8n no **orquestrador central das automações do HubCobrança JACTOS**, preservando o HubCobrança como sistema operacional, o IXC como fonte operacional/financeira e o Python como motor das regras de negócio especializadas que já existem e funcionam.

Arquitetura-alvo:

```text
n8n (ORQUESTRADOR)
  ├─ agenda e coordena
  ├─ executa automações
  ├─ recebe resultados padronizados
  ├─ controla erros/retries
  ├─ centraliza alertas/Telegram
  └─ monitora a saúde das automações
          │
          ├── Python: regras especializadas
          ├── HubCobrança: operação/API/DB
          ├── WhatsApp/Evolution: comunicação
          └── IXC Provedor: dados operacionais/financeiros
```

## 2. PRINCÍPIOS DEFINIDOS

- Auditar o estado real antes de alterar.
- Fazer a menor alteração necessária.
- Preservar funções já validadas.
- Não reescrever o HubCobrança no n8n sem necessidade.
- Python continua responsável por regras de negócio especializadas.
- n8n assume progressivamente a orquestração.
- Mudanças devem ser reversíveis e validadas.
- Não ativar automações em produção sem autorização explícita.
- Não fazer alterações de layout nesta fase; a fase visual está encerrada.
- Não fazer commit/push sem autorização explícita.
- Não misturar automações ClickDF com a operação JACTOS sem necessidade.

## 3. O QUE JÁ FOI CONCLUÍDO

### 3.1 Auditoria e consolidação do HubCobrança

Foi realizado levantamento do aplicativo, banco, integrações, regras de negócio, Serasa, filiais, OS, interações, equipamentos e automações existentes.

### 3.2 Regras de filial

Foi preservada a distinção entre:

- `fn_areceber.filial_id`: filial financeira da cobrança;
- `cliente_contrato.id_filial`: filial operacional do contrato.

Usuários nível 3+ podem trocar a filial ativa; isso é regra de negócio e não deve ser removido.

### 3.3 Primeira cobrança → Segunda cobrança

Regra consolidada: uma interação concluída na primeira cobrança passa para a segunda cobrança quando o pagamento não foi confirmado naquela mesma interação. Se o pagamento foi confirmado, não escala.

Foi feita migração transacional dos registros históricos que estavam incorretamente na primeira cobrança, com backup anterior. Também foi corrigida a lógica do código para novas interações.

### 3.4 Fase visual encerrada

Os módulos do HubCobrança foram revisados e a identidade IaTechHub® foi consolidada. Layout não é mais frente de trabalho deste projeto, salvo necessidade funcional real.

### 3.5 Auditoria das automações

Foram mapeadas as principais automações Python, incluindo auditoria, pagamentos, bloqueios, faturas não liberadas, promessas, parcelas, retiradas, inadimplência, qualidade, retenção, churn, previsão de receita, Serasa, Telegram e manutenção.

Importante: scripts encontrados não significam automaticamente que cada agendamento histórico ainda é o agendamento atual; frequências devem ser reconciliadas antes da migração definitiva.

### 3.6 Arquitetura n8n definida

Foi decidido usar:

- **n8n:** orquestração;
- **Python:** regras especializadas;
- **HubCobrança:** operação e persistência;
- **IXC:** fonte operacional/financeira;
- **Evolution/WhatsApp:** comunicação.

### 3.7 Infraestrutura n8n auditada

O ambiente n8n, PostgreSQL, Redis e Evolution API foi inspecionado. Os workflows existentes foram catalogados e separados entre cobrança e outros projetos.

### 3.8 Workflows oficiais de WhatsApp da cobrança

Foram identificados três workflows como base do domínio de cobrança:

1. **Cobrança WhatsApp - Disparo**
2. **Cobrança WhatsApp - Recepção (Núcleo)**
3. **Handoff Cobrança**

O usuário autorizou a reutilização/modificação desses workflows para JACTOS, pois foram criados para cobrança e não estavam em uso.

### 3.9 API de integração WhatsApp do HubCobrança

A API JACTOS foi preparada/protegida para integração com n8n, incluindo fila, reenvio, registro de interação, abertura de OS, opt-out, pagamento, PIX e sessões.

Foi criada a rota read-only:

`GET /api/whatsapp/identificar`

Ela identifica cliente por CPF/CNPJ e retorna a cobrança elegível mais antiga dentro das regras definidas.

A autenticação por `X-API-Key` foi validada: chave inválida retorna 401 e chave válida acessa a API JACTOS.

### 3.10 Correção do domínio JACTOS

Foi descoberto que workflows antigos apontavam para `cobranca.iatechhub.com.br`, enquanto o backend correto do HubCobrança JACTOS é `cobranca-jactos.iatechhub.com.br`. A integração da cobrança foi direcionada ao domínio correto.

### 3.11 Recepção WhatsApp adaptada

O workflow **Cobrança WhatsApp - Recepção (Núcleo)** foi atualizado diretamente no PostgreSQL do n8n, evitando importação manual do JSON.

Principais mudanças:

- identificação passou a usar a API JACTOS;
- dependência direta antiga do ClickDF foi removida dessa identificação;
- URLs da cobrança foram direcionadas para o domínio JACTOS;
- `Code: Verifica CPF` foi adaptado para consumir o retorno da API JACTOS;
- workflow permaneceu inicialmente inativo durante a alteração;
- backup da versão anterior foi criado no banco.

### 3.12 Publicação e teste da Recepção

O workflow foi publicado e ativado temporariamente com autorização explícita.

O webhook de produção respondeu **HTTP 200** no teste controlado, sem realizar cobrança ou envio ao cliente.

Status atual: **Recepção ativada e webhook funcional; ainda falta o teste funcional completo do fluxo de negócio.**

### 3.13 SentinelX

O acesso de leitura/escrita controlado do SentinelX ao projeto JACTOS foi ajustado usando ACL, sem abrir o projeto com permissões 777. O acesso efetivo de leitura e escrita foi validado.

## 4. ESTADO ATUAL

### 🟢 Concluído

- auditoria do HubCobrança;
- regras principais consolidadas;
- correção primeira → segunda cobrança;
- fase visual encerrada;
- inventário das automações;
- arquitetura n8n definida;
- infraestrutura n8n auditada;
- API WhatsApp JACTOS preparada;
- identificação por CPF/CNPJ funcionando;
- domínio correto JACTOS identificado e aplicado na integração;
- Recepção WhatsApp adaptada;
- Recepção publicada/ativada;
- webhook da Recepção testado com HTTP 200.

### 🟡 Em andamento

- validação funcional completa da Recepção;
- adaptação/validação do Disparo;
- adaptação do Handoff para o escopo exclusivo de cobrança JACTOS;
- integração completa WhatsApp.

### ⏳ Ainda não iniciado/concluído

- orquestrador central da cobrança;
- padronização de retorno das automações Python;
- migração progressiva das automações para serem chamadas pelo n8n;
- central de logs;
- central de alertas;
- health check das automações;
- Telegram centralizado;
- detector de anomalias;
- inteligência operacional.

## 5. PRÓXIMAS ETAPAS OBRIGATÓRIAS

### FASE 1 — Fechar WhatsApp JACTOS

1. Testar funcionalmente a Recepção.
2. Validar o Disparo ponta a ponta.
3. Adaptar e validar o Handoff somente para cobrança.
4. Testar o ciclo completo: entrada → identificação → cobrança → sessão → interação → pagamento/promessa → handoff quando aplicável.
5. Somente depois decidir a ativação operacional definitiva.

### FASE 2 — Criar o Orquestrador n8n

Criar a estrutura lógica:

```text
N8N — COBRANÇA JACTOS
├── 01 Orquestrador
├── 02 Fila de Cobrança
├── 03 Primeira Cobrança
├── 04 Segunda Cobrança
├── 05 Promessas
├── 06 Pagamentos
├── 07 Inadimplência
├── 08 Retiradas
├── 09 Serasa
├── 10 Auditorias
├── 11 Alertas
└── 12 WhatsApp
    ├── Disparo
    ├── Recepção
    └── Handoff
```

### FASE 3 — Integrar automações Python

Para cada automação:

`auditar → entender → padronizar saída → chamar pelo n8n → testar → colocar sob orquestração`.

Não substituir Python automaticamente.

Primeiras candidatas: auditoria geral, resolver pagos, bloqueio antecipado, fatura não liberada, promessas, retiradas, inadimplência e demais automações após classificação.

### FASE 4 — Padronização operacional

Todos os robôs deverão devolver um resultado estruturado, por exemplo:

```json
{
  "automacao": "auditoria_retiradas",
  "execucao": "2026-09-08T08:00:00",
  "status": "OK",
  "duracao": 12.4,
  "processados": 27,
  "alertas": 2,
  "criticos": 1,
  "mensagem": "1 retirada crítica encontrada"
}
```

### FASE 5 — Centralização

Criar no n8n:

- logs de execução;
- tratamento de erros;
- retries controlados;
- Central de Alertas;
- Telegram centralizado;
- relatórios/resumos;
- Health Check.

### FASE 6 — Inteligência

Depois que a operação estiver centralizada e estável:

- detecção de anomalias;
- desvios de promessas;
- picos de cancelamento;
- aumento de inadimplência;
- queda de recuperação;
- falhas recorrentes de integração;
- degradação de desempenho das automações.

## 6. O QUE NÃO FAZER AGORA

- Não mexer novamente no layout.
- Não reescrever o HubCobrança.
- Não reescrever todas as automações Python no n8n.
- Não ativar todos os workflows de uma vez.
- Não misturar ClickDF sem necessidade.
- Não fazer novas melhorias paralelas fora do plano.
- Não retomar auditoria de segurança, salvo solicitação.
- Não fazer commit/push sem autorização.

## 7. MARCO ATUAL DO PROJETO

O próximo marco é:

> **WhatsApp da Cobrança JACTOS completamente validado dentro do n8n.**

Depois:

> **N8N Orquestrador das automações do HubCobrança.**

E somente depois:

> **N8N como cérebro operacional completo da cobrança.**

## 8. CHECKPOINT PARA CONTINUIDADE

Ao retomar este projeto, seguir obrigatoriamente:

`ENTENDER → CONSULTAR A BASE → INVESTIGAR O CÓDIGO → VALIDAR BANCO/CONFIGURAÇÃO → PLANEJAR → IMPLEMENTAR A MENOR ALTERAÇÃO → VALIDAR → TESTAR → REVISAR → REPORTAR → AGUARDAR AUTORIZAÇÃO PARA COMMIT.`

### Regra de foco

Toda nova atividade deve responder primeiro à pergunta:

> **Isso ajuda diretamente a transformar o n8n no orquestrador do HubCobrança JACTOS?**

Se não ajudar, fica fora da frente atual.
