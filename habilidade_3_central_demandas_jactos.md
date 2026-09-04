# HABILIDADE 3 — CENTRAL DE DEMANDAS HUBCOBRANÇA JACTOS

## 1. Identificação

Projeto: HubCobrança JACTOS
Módulo: Central de Demandas
Data: 04/09/2026
Status: IMPLEMENTADO, VALIDADO E COMMITADO

Commit da implementação:

`a87af64 feat(cobranca): adiciona central de demandas no login`

Esta habilidade complementa a Habilidade 1 e a Habilidade 2.

A ordem de consulta para futuras alterações é:

Habilidade 1
→ Habilidade 2
→ Habilidade 3
→ código atual
→ implementação

Nenhuma habilidade posterior substitui as anteriores.

---

## 2. Objetivo

Implementar uma Central de Demandas apresentada automaticamente ao
funcionário ao acessar o HubCobrança.

A Central apresenta as demandas operacionais em ordem de prioridade e
permite entrar diretamente na primeira prioridade disponível.

A implementação não cria uma nova tabela de tarefas, não cria um novo
cron e não cria uma segunda fonte de verdade operacional.

Ela reutiliza estados, interações, promessas e filas existentes.

---

## 3. Prioridades

A ordem oficial é:

### P1 — Nunca Pagaram

Maior prioridade.

Considera clientes elegíveis para a operação Nunca Pagaram dentro da
filial efetiva do usuário.

O contexto funcional de filial utiliza:

`cliente_contrato.id_filial`

Não assumir equivalência automática entre:

`cliente_contrato.id_filial`

e:

`fn_areceber.filial_id`

---

### P2 — Promessas Quebradas

Segunda prioridade.

Utiliza as promessas quebradas já existentes no sistema.

Não cria nova promessa e não transforma automaticamente uma promessa
quebrada em uma nova cobrança.

---

### P3 — Segunda Cobrança

Terceira prioridade.

Utiliza o estado operacional existente:

`segunda_cobranca = 1`

Mantém o acoplamento existente com interações, pagamento e resolução.

---

### P4 — Primeira Cobrança

Quarta prioridade.

Utiliza interações abertas que atendem:

`pago = 0`

`resolvido IS NULL OR resolvido = 0`

`segunda_cobranca IS NULL OR segunda_cobranca = 0`

A ordenação prioriza as faturas mais antigas pela data de vencimento.

---

## 4. Precedência

A ordem é:

P1
→ P2
→ P3
→ P4

O botão principal abre a primeira prioridade que possuir demanda.

Exemplo validado:

P1 = 1
P2 = 0
P3 = 0
P4 = 18

Total:

19

Destino do botão:

P1 — Nunca Pagaram

---

## 5. Não duplicação

As categorias não devem ser simplesmente somadas quando representam o
mesmo item operacional.

A classificação segue a precedência:

P1 vence P2/P3/P4
P2 vence P3/P4
P3 vence P4

A exclusividade é aplicada na montagem do resumo da Central.

A contagem representa entradas operacionais da fila e não uma soma
indiscriminada de todas as subcategorias internas.

---

## 6. Filial efetiva

A filial utilizada pela Central é derivada pelo backend a partir do
usuário autenticado.

O frontend não escolhe a filial.

Fluxo:

login
→ get_usuario()
→ filial efetiva
→ API
→ service
→ consultas

Para usuários que possuem comportamento de troca de filial já previsto
na autenticação, deve ser respeitada a filial efetiva resultante da
sessão.

---

## 7. API

Endpoint:

`/cobranca/api/minhas-demandas`

A API utiliza o usuário autenticado.

O frontend não fornece `usuario_id` como autoridade.

O backend deriva:

- id do usuário;
- nome;
- nível;
- filial efetiva.

Usuários não autenticados não recebem as demandas.

---

## 8. Service

Arquivo:

`app/dashboards/cobranca/service.py`

Função:

`get_minhas_demandas(usuario_id, filial_id)`

Responsabilidades:

1. obter P1;
2. obter P2;
3. obter P3;
4. obter P4;
5. aplicar exclusividade;
6. calcular total;
7. determinar a primeira prioridade disponível;
8. devolver os dados para o frontend.

A função é somente de consulta/classificação.

Não cria tarefas, interações, OS ou promessas.

---

## 9. Nunca Pagaram

Arquivo:

`app/dashboards/cobranca/service_nunca_pagaram.py`

Função adicionada:

`count_nunca_pagaram_filial(filial_id)`

Essa função é específica para a Central.

Ela não altera o comportamento existente da tela:

`/nunca-pagaram`

A regra original da tela não deve ser alterada sem solicitação específica.

---

## 10. Primeira Cobrança — deduplicação

Durante a implementação foi identificado que múltiplas interações abertas
podiam representar a mesma fatura.

Isso podia gerar divergência entre GET e COUNT.

A representação da fila passou a utilizar uma demanda operacional por
fatura.

Quando existem múltiplas interações abertas para a mesma fatura, a
interação mais recente representa a demanda exibida.

As interações históricas não são apagadas.

A deduplicação é somente de representação da fila.

---

## 11. Primeira Cobrança — ordenação

A primeira cobrança utiliza:

`data_vencimento ASC`

As faturas mais antigas aparecem primeiro.

O contexto da filial participa da seleção antes da agregação/seleção da
primeira fatura.

Não selecionar uma primeira fatura global e aplicar a filial somente
depois.

---

## 12. Segunda Cobrança

A Central reutiliza o estado:

`cob_interacoes.segunda_cobranca`

com:

`pago = 0`

e:

`resolvido IS NULL OR resolvido = 0`

Não criar estado paralelo.

Não apagar interações para limpar a tela.

---

## 13. Promessas

A Central utiliza as promessas quebradas existentes.

A promessa quebrada permanece uma categoria própria da Central.

Não assumir que uma promessa quebrada equivale automaticamente a uma
nova cobrança.

Mudanças futuras devem verificar a relação entre:

- cob_interacoes;
- promessas;
- segunda cobrança;
- pagamento;
- resolução;
- crons.

---

## 14. Frontend

Arquivo novo:

`templates/dashboards/_central_demandas.html`

O componente possui:

- modal;
- título;
- resumo;
- quatro prioridades;
- quantidades;
- cores;
- botão principal;
- botão de fechamento;
- abertura automática;
- consulta da API.

Integrações:

`templates/dashboards/cobranca.html`

`templates/dashboards/fila.html`

---

## 15. Comportamento visual

Ao carregar a página:

`DOMContentLoaded`
→ `abrirCentralDemandas()`
→ API
→ renderização

Quando não existem demandas:

"Você não possui demandas pendentes no momento."

Quando existem demandas:

"Você tem X demandas pendentes."

O botão principal recebe dinamicamente a primeira prioridade disponível.

Cores:

P1 — vermelho
P2 — âmbar
P3 — azul
P4 — verde

---

## 16. Navegação

A Central não coloca o estado das demandas na query string.

O botão principal utiliza a rota da prioridade.

A autenticação continua utilizando a sessão/cookie existente.

---

## 17. Segurança

A API não aceita `usuario_id` enviado pelo frontend como autoridade.

Não registrar ou documentar:

- senhas;
- tokens;
- cookies;
- API keys;
- credenciais.

Nenhum segredo deve aparecer nesta habilidade.

Credenciais existentes identificadas durante a investigação devem ser
tratadas separadamente, inclusive quanto à rotação.

---

## 18. Banco de dados

Não houve alteração de schema.

Não foram criadas:

- tabelas;
- colunas;
- migrations.

A implementação reutiliza o banco local e as consultas existentes ao IXC.

Entre as estruturas utilizadas estão:

- `cob_interacoes`;
- `cob_promessas_quebradas`;
- `cob_usuarios`;
- `cliente_contrato`;
- `fn_areceber`.

---

## 19. Idempotência

Abrir a Central repetidamente não cria novos registros.

A Central não cria automaticamente:

- OS;
- interações;
- promessas;
- tarefas;
- alertas.

Ela somente consulta e classifica demandas existentes.

---

## 20. Testes funcionais

### Vitória

Usuário: 4
Filial: 1

P1 = 4
P2 = 1
P3 = 0
P4 = 357
Total = 362

Primeira prioridade: P1

### Graziella

Usuário: 5
Filial: 3

P1 = 1
P2 = 0
P3 = 0
P4 = 21
Total = 22

Primeira prioridade: P1

### Keyla

Usuário: 6
Filial: 2

P1 = 1
P2 = 0
P3 = 0
P4 = 18
Total = 19

Primeira prioridade: P1

---

## 21. Validação da Primeira Cobrança

Após a deduplicação:

Filial 1:

GET = 367
COUNT = 367
distintos = 367
duplicados = 0

Filial 2:

GET = 18
COUNT = 18
distintos = 18
duplicados = 0

Filial 3:

GET = 21
COUNT = 21
distintos = 21
duplicados = 0

A ordenação por data de vencimento também foi validada.

---

## 22. Validação da API

Endpoint:

`/cobranca/api/minhas-demandas`

Foi validado que o endpoint utiliza o usuário autenticado no backend.

Acesso não autenticado foi direcionado ao login.

Não houve exposição de demandas sem autenticação.

---

## 23. Validação de produção

Serviço:

`jactos_cobranca.service`

Porta:

`8019`

Após a implementação o serviço foi reiniciado.

Resultado observado:

`Application startup complete.`

`Uvicorn running on http://127.0.0.1:8019`

Status:

`active`

Login:

HTTP 200

---

## 24. Validação visual

Foi realizado teste visual com usuário real.

Usuária:

Keyla

Resultado:

P1 Nunca Pagaram = 1
P2 Promessas Quebradas = 0
P3 Segunda Cobrança = 0
P4 Primeira Cobrança = 18

Total:

19

O botão principal exibiu:

"Ver nunca pagaram"

Resultado:

- modal abriu;
- contagens corretas;
- prioridades corretas;
- cores corretas;
- primeira prioridade identificada;
- integração visual funcionando.

---

## 25. Backup

Backup realizado antes do commit:

`/opt/backup/jactos-cobranca/central_demandas_final_20260904_050019/cobranca-central-demandas.tar.gz`

Tamanho observado:

291K

---

## 26. Arquivos alterados

Backend:

`app/dashboards/cobranca/router.py`

`app/dashboards/cobranca/service.py`

`app/dashboards/cobranca/service_nunca_pagaram.py`

Frontend:

`templates/dashboards/cobranca.html`

`templates/dashboards/fila.html`

`templates/dashboards/_central_demandas.html`

---

## 27. Git

Commit:

`a87af64`

Mensagem:

`feat(cobranca): adiciona central de demandas no login`

Após o commit:

working tree limpa.

A implementação foi versionada separadamente da documentação desta
habilidade.

---

## 28. Não alterado

Esta implementação não alterou:

- schema;
- framework;
- arquitetura;
- mecanismo de autenticação;
- pagamentos;
- crons;
- OS246;
- OS39;
- OS38;
- WhatsApp;
- Telegram.

---

## 29. Riscos e pendências

### Telegram

Foi identificada anteriormente uma credencial Telegram hardcoded no
código.

O valor não deve ser registrado nesta documentação.

A rotação deve ser tratada como etapa separada.

### Permissões

A matriz completa de níveis JACTOS deve continuar sendo consultada no
código e na Base de Conhecimento.

Não importar regras de outro projeto.

### Promessas

Não assumir comportamentos que não estejam confirmados no código JACTOS.

### Crons

Não importar horários ou comportamentos do CliqueDF.

---

## 30. Lições técnicas

1. Reutilizar estados operacionais evita múltiplas fontes de verdade.
2. Demandas sobrepostas exigem precedência antes da contagem.
3. A filial precisa participar do universo funcional correto.
4. GET e COUNT devem representar o mesmo universo.
5. Deduplicação de tela não significa exclusão de histórico.
6. Service testado não substitui teste com usuário real.
7. A primeira prioridade disponível deve controlar o botão principal.
8. Abrir a Central não pode produzir efeitos colaterais.

---

## 31. Regra para futuras alterações

Antes de alterar a Central:

1. consultar Habilidade 1;
2. consultar Habilidade 2;
3. consultar Habilidade 3;
4. ler o código atual;
5. identificar rotas;
6. identificar services;
7. identificar SQL;
8. verificar filial efetiva;
9. verificar permissões;
10. verificar interações;
11. verificar promessas;
12. verificar primeira cobrança;
13. verificar segunda cobrança;
14. verificar pagamentos;
15. avaliar regressões;
16. implementar a menor alteração possível;
17. testar;
18. validar produção;
19. documentar;
20. aguardar autorização de Git.

---

## 32. Banco — regra absoluta

Para UPDATE/DELETE:

SELECT
→ validar registros
→ confirmar regra
→ executar

Nunca executar alteração massiva sem validação.

SQL deve ser seguro e parametrizado.

---

## 33. Regra de Git

Nunca executar:

`git commit`

`git tag`

`git push`

sem autorização explícita do usuário.

A autorização válida é:

"pode commitar"

---

## 34. Estado final

Central de Demandas:

IMPLEMENTADA
VALIDADA
COMMITADA
EM PRODUÇÃO

Commit da implementação:

`a87af64`

Backup:

`central_demandas_final_20260904_050019`

Esta documentação constitui a Habilidade 3 da sequência de conhecimento
do HubCobrança JACTOS.

Próximas alterações devem consultar:

Habilidade 1
→ Habilidade 2
→ Habilidade 3
→ código atual

---

## 35. Princípio final

Entender
→ consultar a base
→ consultar Habilidade 1
→ consultar Habilidade 2
→ consultar Habilidade 3
→ investigar código
→ planejar
→ implementar
→ testar
→ validar produção
→ documentar
→ aguardar autorização de Git
