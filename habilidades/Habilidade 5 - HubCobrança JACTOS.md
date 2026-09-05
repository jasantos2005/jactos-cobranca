# Habilidade 5 — HubCobrança JACTOS

## 1. MARCO DE CONTINUIDADE

Esta habilidade consolida o estado do projeto após a Habilidade 4.

Habilidade 4:
- Arquivo: `/opt/automacoes/jactos/cobranca/habilidades/Habilidade 4 - HubCobrança JACTOS.md`
- Commit-base: `a99727f`

Data de consolidação:
- 05/09/2026 23:48:24

---

# 2. OBJETIVO DA HABILIDADE 5

Registrar tudo que foi analisado, corrigido, validado ou decidido após a Habilidade 4, mantendo uma base técnica para continuidade segura do projeto.

A regra principal permanece:

> Não alterar código ou banco de forma ampla sem primeiro entender o fluxo, validar a hipótese e executar alteração controlada.

Toda alteração em banco deve seguir:
1. diagnóstico;
2. consulta somente leitura;
3. validação;
4. backup;
5. alteração transacional;
6. verificação pré-commit;
7. commit;
8. verificação pós-commit.

---

# 3. FILIAL — REGRA DEFINITIVA

A filial operacional do usuário NÃO deve ser confundida com a filial da OS.

Foi confirmado que:

- usuários nível 3 ou superior podem trocar a filial ativa;
- essa troca é uma funcionalidade legítima;
- não deve ser removida;
- `cob_usuarios.filial_id` representa a filial inicial/default;
- a filial ativa pode ser alterada pelo usuário autorizado.

## Regra da OS

A filial da OS deve vir exclusivamente do contrato:

`cliente_contrato.id_filial`

Não utilizar:
- filial fixa 1;
- filial do usuário;
- filial do cliente como fallback;
- última OS do cliente como fonte de filial.

Quando não houver contrato válido ou filial válida:

> BLOQUEAR a criação da OS.

Nunca utilizar fallback silencioso para filial 1.

Arquivo responsável:

`app/core/filial_scope.py`

Função:

`resolver_filial_contrato(id_contrato)`

---

# 4. EQUIPAMENTOS

Foi confirmado o relacionamento:

- `movimento_produtos.id_contrato`
- `cliente_contrato.id`
- `cliente_contrato.id_cliente`
- `cliente_contrato.id_filial`

Também foi confirmado que `movimento_produtos` possui:
- `filial_id`
- `id_contrato`
- `id_oss_chamado`
- `status_comodato`

Não existe `movimento_produtos.id_cliente`.

Portanto, para determinar cliente/filial pelo equipamento:

`movimento_produtos -> cliente_contrato`

---

# 5. ASSUNTOS DE OS — PADRÃO JACTOS

## Retirada

Assunto correto:

`34 — [OP] RETIRAR EQUIPAMENTOS`

## Cobrança em andamento

O antigo assunto ClickDF:

`246`

foi substituído por:

`190 — COBRANCA EM ANDAMENTO`

## Auditoria de cancelamento

O antigo assunto ClickDF:

`38`

foi substituído por:

`171 — assunto JACTOS correspondente`

## Assunto 39

`39` NÃO deve ser substituído globalmente.

Ele possui uso legítimo como:

`SINAL ALTO`

Portanto:

> Nunca fazer substituição global de todos os números 39.

---

# 6. FLUXO DE SEGUNDA COBRANÇA

Foram identificadas implementações duplicadas de segunda cobrança.

A duplicidade foi removida.

Deve existir apenas uma implementação de:

`count_segunda_cobranca`

e uma implementação de:

`mover_para_segunda_cobranca`

A segunda cobrança utiliza o assunto JACTOS:

`190`

Antes de movimentar a interação para segunda cobrança:

1. localizar fatura;
2. obter cliente;
3. obter contrato;
4. validar contrato;
5. resolver filial pelo contrato;
6. somente então alterar/inserir a interação;
7. verificar/criar OS 190.

Não alterar a base local antes da validação do contrato/filial.

---

# 7. ABERTURA DE OS

Foram eliminados fluxos antigos/duplicados de abertura de OS.

A abertura deve seguir as regras:

## OS 34

Para retirada de equipamento.

## OS 190

Para cobrança em andamento/segunda cobrança.

## OS 171

Para o fluxo relacionado à auditoria de cancelamento/material recolhido.

Sempre que a OS estiver relacionada a uma fatura:

`fn_areceber.id -> id_contrato -> cliente_contrato.id_filial`

---

# 8. DASHBOARD DE INADIMPLÊNCIA

Foi concluída a migração do indicador de cidade para bairro.

Endpoint atual:

`/cobranca/api/inadimplencia-por-bairro`

Frontend:

`templates/dashboards/cobranca.html`

Service:

`get_inadimplencia_por_bairro()`

O indicador atual apresenta:

- bairro;
- quantidade de clientes;
- quantidade inadimplente;
- taxa;
- quantidade de títulos;
- valor aberto.

Último teste validado:

- 105 bairros;
- 595 clientes considerados;
- 595 clientes inadimplentes;
- 632 títulos;
- R$ 104.816,23 em aberto.

O dashboard foi atualizado visualmente para:

**Inadimplência por Bairro**

A referência antiga:

`/cobranca/api/inadimplencia-por-cidade`

foi removida do frontend.

---

# 9. PADRONIZAÇÃO DE BAIRROS

Foi feita auditoria extensa do cadastro de bairros do IXC.

Regra definitiva:

> Não tentar eliminar diferenças legítimas entre bairros.

Exemplos que devem ser preservados:

- VILA MUTIRÃO
- VILA MUTIRÃO I
- VILA MUTIRÃO II
- JARDIM CURITIBA
- JARDIM CURITIBA IV
- JARDIM NOVO MUNDO
- JARDIM NOVO MUNDO 3
- CANDIDA DE MORAES
- SETOR CÂNDIDA DE MORAIS

CEP é apenas referência.

CEP genérico não pode ser usado sozinho para decidir que dois bairros são iguais.

## Correções efetivamente realizadas

Foram feitas correções controladas de erros evidentes de cadastro.

Primeiro lote:
- 6 clientes.

Segundo lote:
- 31 clientes.

Total efetivamente alterado:

**37 clientes**

Todas as alterações foram:
- validadas por ID;
- executadas com transação;
- verificadas antes do commit;
- verificadas depois do commit;
- acompanhadas de backup.

Nenhuma alteração de INSERT ou DELETE foi realizada.

---

# 10. SEGURANÇA JWT

Foi corrigido:

## SECRET_KEY

O fallback inseguro foi removido.

Agora:

`SECRET_KEY` é obrigatória no `.env`.

Se não existir:

`RuntimeError`

## Cookie

O cookie de autenticação passou a utilizar:

- HttpOnly;
- Secure;
- SameSite=Lax;
- Max-Age.

## .env

Permissão ajustada para:

`600`

A etapa de segurança JWT foi validada e aprovada.

---

# 11. TELEGRAM

Foi identificado token Telegram hardcoded em vários arquivos.

Foi criada uma centralização:

`/opt/automacoes/core/telegram.py`

Também existe o helper específico:

`app/core/telegram.py`

Arquivos principais do HubCobrança foram migrados para usar o helper.

A rotação do token não foi executada neste momento porque o mesmo bot/token é compartilhado por múltiplas aplicações e a criação de novos bots possui limitação operacional.

Regra:

> Nunca gravar novamente token Telegram literalmente no código.

---

# 12. DEPENDÊNCIA CLICKDF

Foi identificado que o HubCobrança JACTOS ainda fazia leituras do banco:

`/opt/automacoes/cliquedf/comercial/hub_comercial.db`

Foi definido como regra arquitetural:

> O HubCobrança JACTOS não deve depender do Hub Comercial ClickDF.

Parte das consultas foi migrada para o IXC e/ou banco local JACTOS.

Foram especialmente tratados serviços como:

- qualidade;
- cancelamentos;
- cancelamentos por inadimplência;
- nunca pagaram;
- resultado NP;
- retenção;
- gerencial.

Ainda deve ser feita uma auditoria final para garantir:

> zero leitura ativa do Hub Comercial ClickDF.

---

# 13. QUALIDADE DE VENDAS

O serviço de qualidade foi migrado para trabalhar com dados do IXC.

Foram preservados os indicadores necessários.

Foi validado:

- contratos;
- vendas;
- vendedores;
- pagamentos;
- ranking;
- score.

A contagem histórica de pagamentos utiliza títulos pagos no IXC (`status='R'`).

---

# 14. BAIRROS — COBERTURA DO INDICADOR

Foi descoberto que uma matriz local anterior de CEP/bairro não representava adequadamente todo o universo.

A matriz apresentava grande quantidade de clientes sem correspondência aprovada.

Por isso:

> A matriz local não deve ser tratada como fonte definitiva do bairro.

O indicador passou a usar diretamente:

`ixcprovedor.cliente.bairro`

Isso simplifica a arquitetura e evita que uma matriz incompleta distorça o dashboard.

---

# 15. PROCESSO DE ALTERAÇÃO DO IXC

Nunca executar atualização massiva baseada somente em similaridade textual.

Processo aprovado:

1. detectar candidato;
2. mostrar ID;
3. mostrar cliente;
4. mostrar CEP;
5. mostrar bairro atual;
6. mostrar bairro proposto;
7. validar individualmente;
8. fazer backup;
9. executar UPDATE transacional;
10. validar row count;
11. verificar dados antes do commit;
12. COMMIT;
13. verificar novamente depois do commit.

---

# 16. ESTADO ATUAL DO DASHBOARD

Backend:

`/api/kpis`

`/api/top10-devedores`

`/api/inadimplencia-por-bairro`

`/api/evolucao`

Frontend:

`carregarKPIs()`

`carregarTop10()`

`carregarBairros()`

`carregarGrafico()`

Título atual:

**Inadimplência por Bairro**

O endpoint antigo de cidade não deve retornar ao dashboard.

---

# 17. PROBLEMA OBSERVADO NO RESTART

Durante testes de restart foi observado no log:

`sqlite3.OperationalError: no such table: cob_retencao_resultados`

Origem:

`app/dashboards/cobranca/service_gerencial.py`

Isso indica que existe ainda uma dependência do dashboard gerencial em uma tabela SQLite que não está presente no banco local esperado.

Esse ponto deve permanecer como pendência técnica.

Não mascarar o erro com `except: pass`.

---

# 18. PRINCIPAIS PENDÊNCIAS PARA A HABILIDADE 6

## Prioridade alta

1. Auditar e eliminar definitivamente todas as leituras ativas do ClickDF Comercial pelo JACTOS.
2. Corrigir `cob_retencao_resultados` no dashboard gerencial.
3. Fazer auditoria final de todas as rotinas de criação de OS.
4. Garantir que nenhuma OS use filial fixa/fallback.
5. Revisar todos os `except: pass` relacionados a IXC/API/Telegram.
6. Revisar os fluxos duplicados restantes.
7. Criar testes automatizados mínimos para:
   - filial;
   - OS 34;
   - OS 171;
   - OS 190;
   - segunda cobrança;
   - inadimplência por bairro.

## Prioridade média

8. Finalizar centralização de Telegram.
9. Revisar bootstrap/migrações.
10. Revisar SQL interpolado.
11. Melhorar logs de erros externos.
12. Revisar dependências SQLite.

---

# 19. REGRA DE OURO DO PROJETO

Antes de qualquer correção:

**NÃO ALTERAR.**

Primeiro:

**ENTENDER → CONSULTAR → VALIDAR → BACKUP → ALTERAR → TESTAR → COMMITAR.**

Especialmente para:

- IXC;
- OS;
- filial;
- cobrança;
- equipamentos;
- dados financeiros.

---

# 20. COMMITS POSTERIORES À HABILIDADE 4

2d86f68 security: centralizar credenciais do Telegram
41787fb chore: remover rotina legada de abertura de OS

---

# 21. CONDIÇÃO DE FECHAMENTO

Esta Habilidade 5 deve ser considerada o novo ponto de continuidade do projeto.

O próximo trabalho deve partir daqui, sem repetir as auditorias já concluídas.

Backup gerado nesta consolidação:

`/opt/automacoes/jactos/cobranca/backups/hubcobranca_jactos_pre_habilidade5_20260905_234823.tar.gz`

