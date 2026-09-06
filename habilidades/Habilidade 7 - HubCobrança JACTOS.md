# Habilidade 7 — HubCobrança JACTOS
## Módulo Serasa, patrimônio, comodato e continuidade de segurança

**Projeto:** HubCobrança JACTOS  
**Etapa:** Habilidade 7  
**Objetivo:** consolidar o trabalho realizado na etapa de criação e refinamento do módulo Serasa, incluindo visão financeira, patrimônio, histórico, entradas/saídas do Serasa, busca por CPF/CNPJ e interpretação correta da localização dos equipamentos.

---

## 1. MÓDULO SERASA

Foi criado um módulo dedicado ao acompanhamento dos clientes relacionados ao Serasa.

### Página de clientes atualmente no Serasa

Rota:

`/cobranca/serasa`

A página apresenta:

- quantidade de clientes atualmente no Serasa;
- valor financeiro;
- quantidade somente financeira;
- quantidade somente equipamento;
- quantidade com financeiro + equipamento;
- quantidade de equipamentos;
- CPF/CNPJ;
- última negativação;
- valor financeiro;
- valor dos equipamentos;
- quantidade de equipamentos;
- classificação.

A tabela inicialmente apresenta os últimos 30 clientes por data de negativação.

Também existe pesquisa por CPF/CNPJ, permitindo localizar clientes fora dos 30 inicialmente exibidos.

---

## 2. UNIVERSO ATUAL DO SERASA

A identificação dos clientes atualmente no Serasa não deve depender exclusivamente de `cliente.ativo_serasa`.

A regra adotada considera as negativações existentes:

- `negativacao_spc_serasa.status = 1`;
- ausência de registro correspondente em `remocao_spc_serasa`.

Validação realizada no banco:

- 1.540 negativações com status 1;
- 1.192 clientes atualmente negativados;
- 277 negativações com status 2;
- 227 clientes relacionados ao status 2.

Portanto, para o módulo atual, o universo operacional de clientes no Serasa é baseado nas negativações ativas sem remoção.

---

## 3. VALOR FINANCEIRO

O valor financeiro é calculado a partir das negativações e respectivas faturas.

A classificação considera a existência de débito financeiro ativo e de equipamento pendente.

Categorias:

- somente financeiro;
- somente equipamento;
- financeiro + equipamento.

---

## 4. VALOR DO EQUIPAMENTO

Foi identificada e corrigida uma interpretação importante.

O valor oficial do equipamento utilizado pelo módulo é:

`produtos.valor`

A relação é:

`patrimonio.id_produto -> produtos.id`

Não deve ser utilizado `patrimonio.valor_bem` como fonte principal do valor do equipamento.

Exemplo validado:

Patrimônio 3927:

- produto: ONT TENDA HG15;
- `produtos.valor`: R$ 259,90;
- `patrimonio.valor_bem`: R$ 149,00.

Portanto, para o Hub, o valor considerado é R$ 259,90.

Validação do universo atual:

- 1.192 clientes;
- 593 clientes com equipamentos;
- valor total dos equipamentos: R$ 130.536,40;
- valor financeiro total: R$ 720.669,99.

---

## 5. HISTÓRICO DO CLIENTE

Foi criado endpoint para consulta detalhada:

`/cobranca/api/serasa/cliente/{id_cliente}`

O retorno contém:

- dados do cliente;
- CPF/CNPJ;
- situação/classificação;
- valor financeiro;
- valor dos equipamentos;
- equipamentos vinculados;
- histórico de negativações;
- datas de negativação;
- datas de baixa/remoção;
- informações das faturas.

O retorno utiliza `jsonable_encoder` para garantir serialização correta de datas e demais tipos vindos do MySQL.

---

## 6. PÁGINA DE SAÍDAS DO SERASA

Rota:

`/cobranca/serasa/saidas`

Endpoint:

`/cobranca/api/serasa/saidas`

A página apresenta inicialmente os últimos 30 registros de saída.

Campos:

- cliente;
- CPF/CNPJ;
- entrada no Serasa;
- saída do Serasa;
- valor financeiro;
- valor equipamento;
- fatura;
- forma da remoção.

Também existe pesquisa por CPF/CNPJ.

Validação realizada:

- 278 saídas;
- 278 negativações distintas;
- nenhuma duplicidade de negativação.

A relação correta para a saída é:

`negativacao_spc_serasa.id -> remocao_spc_serasa.id_negativacao`

A data de saída é `remocao_spc_serasa.data_baixa`.

---

## 7. EQUIPAMENTOS E ÚLTIMA MOVIMENTAÇÃO

Foi identificada uma regra crítica do IXC.

O campo:

`patrimonio.id_almoxarifado`

não deve ser utilizado isoladamente para determinar a localização física atual do equipamento.

O estado atual deve ser interpretado pela última movimentação em:

`patrimonio_movimentacao`

A consulta considera:

- `pm.id_patrimonio`;
- `pm.id_contrato`;
- `pm.cliente_destino`;
- `pm.data_movimentacao`;
- cadastro do patrimônio;
- produto relacionado.

A última movimentação prevalece sobre o almoxarifado armazenado no cadastro do patrimônio.

---

## 8. REGRA DE COMODATO

Quando a última movimentação mantém:

- contrato válido;
- cliente de destino;

o patrimônio está associado ao cliente.

Nesse cenário, mesmo que `patrimonio.id_almoxarifado` tenha um valor, isso não significa que o equipamento esteja fisicamente naquele estoque.

A classificação atual é:

`comodato`

com descrição:

`Em comodato / com cliente`

e pendência:

`True`

---

## 9. CASO VALIDADO — PATRIMÔNIO 4249

Patrimônio:

`4249`

Equipamento:

`ONT TENDA HG9`

Valor oficial:

`R$ 220,00`

Cliente:

`Danilo Santos Correia`

Contrato:

`24429`

Última movimentação:

`19039`

Data:

`20/10/2025 16:54:56`

Cliente destino:

`23066`

Almoxarifado cadastrado:

`27`

Apesar do patrimônio possuir `id_almoxarifado = 27`, a última movimentação mantém o equipamento em comodato com o cliente.

O teste do Hub passou a retornar:

- `status = comodato`;
- `status_label = Em comodato / com cliente`;
- `pendente = True`.

Portanto, o equipamento não deve aparecer como "No estoque".

---

## 10. INTERPRETAÇÃO DE EQUIPAMENTO NÃO DEVOLVIDO

A regra de negócio definida nesta etapa é que o sistema precisa deixar evidente quando o equipamento continua em comodato e existe pendência de devolução.

No modal, além do status, existe agora indicação:

`Devolução: ⚠️ Pendente`

Importante:

`status = N` no contrato IXC significa situação de negativação e não deve ser tratado automaticamente como cancelamento.

Também não se deve considerar `status_internet = D` isoladamente como prova suficiente de cancelamento.

O status de contrato `I` é utilizado pelo próprio Hub em fluxos de cancelamento/inatividade e representa contrato inativo.

A classificação definitiva de "Não devolvido" deve ser aplicada somente quando houver evidência suficiente de encerramento do contrato e permanência do patrimônio em comodato.

---

## 11. STATUS DE CONTRATO VALIDADO

Distribuição encontrada em `cliente_contrato.status`:

- `A`: 6.742;
- `I`: 4.621;
- `P`: 10;
- `N`: 1.368;
- `D`: 260.

Não atribuir significado adicional a `P` ou `D` sem validação específica.

No caso do contrato 24429:

- `status = N`;
- `status_internet = D`;
- `motivo_cancelamento = 0`;
- `data_cancelamento = 0000-00-00`.

Na tela do IXC, o contrato aparece como negativado e o acesso como desativado.

---

## 12. REGRAS DE ESTADO DO EQUIPAMENTO

A lógica consolidada nesta etapa é:

1. última movimentação vinculada a cliente/contrato:
   - equipamento está com cliente/em comodato;

2. movimentação posterior indicando retorno a almoxarifado:
   - equipamento volta a ser considerado estoque;

3. movimentação indicando estoque do técnico:
   - equipamento fica associado ao técnico;

4. almoxarifado especial 29:
   - perdido;

5. almoxarifado especial 16:
   - avaria;

6. `patrimonio.id_almoxarifado` isoladamente:
   - não determina a localização física atual.

---

## 13. SEGURANÇA E INFRAESTRUTURA CONSOLIDADAS NAS ETAPAS ANTERIORES

O projeto também possui as seguintes correções consolidadas:

### JWT

- `SECRET_KEY` não possui mais fallback inseguro;
- a aplicação exige `SECRET_KEY` no `.env`;
- cookie `access_token` utiliza:
  - HttpOnly;
  - Secure;
  - SameSite=Lax;
  - Max-Age.

`.env` está com permissão restrita.

### Telegram

Foi criado helper global:

`/opt/automacoes/core/telegram.py`

O HubCobrança passou a utilizar configuração centralizada em vez de manter o token diretamente no código.

A rotação do token compartilhado foi deliberadamente postergada porque o mesmo bot/token é utilizado por outros aplicativos.

### Filial

A filial da OS deve ser determinada pelo contrato:

`cliente_contrato.id_filial`

Não utilizar filial fixa ou fallback para filial 1.

A função central é:

`resolver_filial_contrato(id_contrato)`

Contratos inválidos ou sem filial válida devem bloquear a criação da OS.

A possibilidade de usuários de nível 3+ alternarem a filial de trabalho é uma regra de negócio intencional e não deve ser removida.

---

## 14. ASSUNTOS DE OS

Correções consolidadas:

- assunto 34:
  - RETIRAR EQUIPAMENTOS;

- assunto 190:
  - COBRANCA EM ANDAMENTO;
  - substituição do legado 246;

- assunto 171:
  - substituição do legado 38;

- assunto 39:
  - permanece legítimo para SINAL ALTO;
  - não deve ser substituído globalmente.

---

## 15. SEGUNDA COBRANÇA

Foi eliminada a duplicidade das funções de segunda cobrança.

Permanece uma implementação de:

`count_segunda_cobranca`

e uma implementação de:

`mover_para_segunda_cobranca`

O assunto utilizado para segunda cobrança é:

`190 — COBRANCA EM ANDAMENTO`

A filial da OS é resolvida pelo contrato.

---

## 16. VALIDAÇÕES REALIZADAS

Foram executadas validações de:

- compilação Python;
- importação dos módulos;
- serialização JSON;
- consultas reais no IXC;
- relacionamento patrimônio/contrato/cliente;
- relacionamento patrimônio/produto;
- cálculo de valores;
- quantidade de clientes no Serasa;
- quantidade de saídas;
- ausência de duplicidades;
- resolução de filial;
- bloqueio de contrato inválido;
- classificação do patrimônio 4249.

O patrimônio 4249 foi validado diretamente e retornou:

`Em comodato / com cliente`

com pendência de devolução.

---

## 17. INTERFACE

As páginas receberam:

### Clientes no Serasa

- tabela de clientes;
- CPF/CNPJ;
- última negativação;
- valores;
- classificação;
- modal detalhado;
- histórico;
- equipamentos;
- patrimônio;
- serial;
- MAC;
- status;
- indicação de devolução pendente;
- busca por CPF/CNPJ;
- apresentação inicial dos últimos 30.

### Saídas do Serasa

- tabela dos últimos 30;
- CPF/CNPJ;
- entrada;
- saída;
- valores;
- forma de remoção;
- busca por CPF/CNPJ;
- modal/histórico.

Os campos de busca foram padronizados para aproximadamente 240 px, evitando ocupar toda a largura da página.

---

## 18. ARQUIVOS PRINCIPAIS DA HABILIDADE 7

Novos arquivos:

- `app/dashboards/cobranca/service_serasa.py`
- `templates/dashboards/serasa.html`
- `templates/dashboards/serasa_saidas.html`
- `habilidades/Habilidade 7 - HubCobrança JACTOS.md`

Arquivos alterados nesta etapa:

- `app/dashboards/cobranca/router.py`
- `templates/_sidebar.html`

---

## 19. PRINCÍPIO FUNDAMENTAL PARA CONTINUIDADE

Ao trabalhar com patrimônio no HubCobrança:

**Nunca concluir que um equipamento está em estoque apenas porque `patrimonio.id_almoxarifado` possui um valor.**

Sempre analisar a última movimentação do patrimônio.

Quando a última movimentação indicar comodato com cliente, o equipamento deve ser tratado como estando com o cliente.

Quando houver encerramento comprovado do vínculo e não existir movimentação posterior de devolução, o sistema deve destacar a pendência de devolução.

---

## 20. ESTADO DE ENCERRAMENTO DA HABILIDADE 7

A Habilidade 7 consolida a criação e refinamento do módulo Serasa e a correção da interpretação patrimonial.

O estado deve ser preservado por backup e commit antes de iniciar novas alterações.

Não realizar novas alterações funcionais nesta etapa após a criação deste documento sem registrar uma nova etapa/habilidade ou atualização controlada desta habilidade.
