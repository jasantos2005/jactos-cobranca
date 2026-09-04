# HABILIDADE 3 — HUBCOBRANÇA
## Documento de Continuidade, Arquitetura, Regras e Segurança

**Projeto:** HubCobrança  
**Empresa:** JACTOS  
**Diretório:** `/opt/automacoes/jactos/cobranca`  
**Data:** 04/09/2026  
**Versão:** 3

---

# 1. OBJETIVO DESTE DOCUMENTO

Este documento registra o conhecimento consolidado sobre o HubCobrança,
suas regras de negócio, arquitetura, banco de dados, integrações,
problemas identificados, correções realizadas e pontos que ainda precisam
ser tratados.

A finalidade é impedir que futuras alterações sejam realizadas sem
entendimento suficiente do sistema.

Este documento deve ser consultado antes de alterações estruturais no
HubCobrança.

---

# 2. REGRA PRINCIPAL DE MANUTENÇÃO

Nunca alterar uma regra apenas porque o código atual parece incorreto.

Antes de modificar:

1. identificar a origem do dado;
2. entender a regra de negócio;
3. consultar o banco de dados;
4. identificar todos os pontos que utilizam aquela informação;
5. verificar se existem múltiplos caminhos para a mesma operação;
6. testar sem escrita sempre que possível;
7. somente depois realizar alteração em produção.

Alterações grandes e indiscriminadas devem ser evitadas.

Preferir alterações cirúrgicas, uma etapa por vez.

---

# 3. ARQUITETURA

O HubCobrança é uma aplicação FastAPI executada com Uvicorn.

Principais características:

- FastAPI;
- Jinja2;
- JavaScript vanilla;
- Fetch API;
- Chart.js;
- JWT em cookie;
- MySQL do IXC;
- SQLite local;
- routers;
- services;
- crons;
- integração com API do IXC;
- integração com WhatsApp;
- integração com Telegram.

O projeto possui arquitetura monolítica, com diversos módulos responsáveis
por diferentes partes da operação.

Não existe atualmente uma camada ORM/repository centralizada.

Existem diversos pontos que executam SQL diretamente.

---

# 4. BANCO DE DADOS

## 4.1 IXC MySQL

Banco:

`ixcprovedor`

Principais tabelas utilizadas:

- `cliente`
- `cliente_contrato`
- `fn_areceber`
- `su_oss_chamado`
- `movimento_produtos`
- `patrimonio_movimentacao`
- `patrimonio`
- `almox`

## 4.2 Banco local

SQLite local utilizado pelo HubCobrança.

Principais tabelas:

- `cob_usuarios`
- `cob_interacoes`

---

# 5. USUÁRIOS E FILIAIS

Tabela local:

`cob_usuarios`

Campos importantes:

- `id`
- `nome`
- `login`
- `setor`
- `nivel`
- `aprovado`
- `ativo`
- `filial_id`

Filiais atualmente utilizadas:

- `0` = Todas
- `1` = Matriz
- `2` = Novo Mundo
- `3` = Solange Park

---

# 6. REGRA FUNDAMENTAL DAS FILIAIS

A filial do operador NÃO determina a filial da OS.

O operador pode possuir uma filial padrão, mas usuários de nível
suficiente podem trocar a filial ativa para auxiliar outra unidade.

Essa troca é uma funcionalidade intencional do sistema.

Portanto:

## NÃO ALTERAR O MECANISMO DE TROCA DE FILIAL.

A filial operacional do operador e a filial da OS são conceitos diferentes.

---

# 7. REGRA FUNDAMENTAL DA FILIAL DA OS

A filial da OS deve ser determinada pelo:

`cliente_contrato.id_filial`

A origem correta é:

```text
Fatura
  ↓
fn_areceber.id_contrato
  ↓
cliente_contrato.id
  ↓
cliente_contrato.id_filial
