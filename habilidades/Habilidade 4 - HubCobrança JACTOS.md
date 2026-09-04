# HABILIDADE 4 — HubCobrança JACTOS
## Auditoria de criação de OS, filial por contrato, assuntos e integridade dos fluxos

**Projeto:** HubCobrança JACTOS  
**Sistema:** FastAPI + MySQL IXC + SQLite local  
**Data de consolidação:** 04/09/2026  
**Objetivo desta habilidade:** registrar as regras, correções, testes e método de manutenção aprendidos durante a auditoria de segurança e consistência dos fluxos de cobrança e retirada.

---

# 1. OBJETIVO DA HABILIDADE

Esta habilidade consolida o conhecimento adquirido durante a auditoria dos fluxos de criação e movimentação de Ordens de Serviço (OS) do HubCobrança JACTOS.

O foco principal foi garantir que:

- cada OS seja criada com o assunto correto;
- a filial da OS seja determinada pela origem operacional correta;
- a filial seja derivada do contrato quando a OS estiver vinculada a uma cobrança;
- clientes com múltiplos contratos não sejam tratados como se tivessem uma única filial;
- faturas sem contrato não provoquem criação de OS com filial incorreta;
- não exista fallback silencioso para filial 1;
- fluxos antigos do ClickDF não contaminem o sistema JACTOS;
- todos os caminhos de criação de OS sejam auditados;
- alterações sejam feitas de forma cirúrgica e validada;
- testes de alteração não criem OS reais desnecessariamente.

---

# 2. REGRA FUNDAMENTAL APRENDIDA

## Cadeia oficial para cobrança

Quando uma OS de cobrança ou retirada nasce de uma fatura, a cadeia correta é:

    FATURA
       ↓
    fn_areceber.id_contrato
       ↓
    cliente_contrato.id
       ↓
    cliente_contrato.id_filial
       ↓
    OS.id_filial

A regra é:

> A filial da OS deve ser determinada pelo contrato relacionado à fatura.

Não se deve determinar a filial apenas pelo cliente.

---

# 3. CLIENTE PODE TER VÁRIOS CONTRATOS

Um mesmo cliente pode possuir vários contratos ativos em filiais diferentes.

Portanto:

    cliente → filial

NÃO é uma relação confiável para criação de OS.

A relação correta é:

    fatura → contrato → filial

Exemplo validado durante a auditoria:

Um mesmo cliente pode possuir:

- contrato em filial 3;
- outro contrato em filial 1;
- outro contrato novamente em filial 3.

Logo, se uma fatura estiver vinculada ao contrato da filial 2, a OS daquela cobrança deve ser criada na filial 2, independentemente da filial atual do cliente.

---

# 4. NUNCA USAR FILIAL 1 COMO FALLBACK

Foi identificada a necessidade de eliminar a lógica implícita de:

    "se não sei a filial, uso 1"

Essa prática é proibida.

Quando não for possível determinar a filial:

1. bloquear a criação da OS;
2. registrar o motivo no log;
3. permitir que o problema seja corrigido na origem.

Casos que devem bloquear:

- fatura sem contrato;
- contrato inexistente;
- contrato com filial inválida;
- contrato inválido;
- cadeia fatura → contrato inconsistente.

---

# 5. FUNÇÃO CENTRAL DE RESOLUÇÃO DA FILIAL

Foi criada/consolidada a responsabilidade em:

    app/core/filial_scope.py

Função:

    resolver_filial_contrato(id_contrato)

Comportamento:

1. converte o ID do contrato;
2. rejeita contrato inválido;
3. consulta `cliente_contrato`;
4. verifica se o contrato existe;
5. lê `id_filial`;
6. rejeita filial inválida;
7. retorna a filial válida.

Exemplos testados:

    contrato 26107 → filial 1
    contrato 25448 → filial 3
    contrato 7263  → filial 1

Contratos inválidos:

    0
    None
    999999999

devem ser bloqueados.

---

# 6. ASSUNTOS OFICIAIS DE OS DO JACTOS

Durante a auditoria foi feita a distinção entre assuntos legados do ClickDF e assuntos utilizados pelo JACTOS.

## OS 34

    [OP] RETIRAR EQUIPAMENTOS

Uso:

- retirada de equipamento;
- retirada acelerada;
- fluxos relacionados à devolução física do equipamento.

A OS 34 deve receber `id_filial` derivado do contrato quando o fluxo possuir fatura/contrato.

---

## OS 171

Uso:

- substituição JACTOS do fluxo legado relacionado ao assunto 38;
- material recolhido;
- devolução ao estoque.

Quando criada a partir de cobrança, a filial deve ser derivada do contrato da fatura.

---

## OS 190

Uso:

    COBRANCA EM ANDAMENTO

É o assunto JACTOS utilizado no lugar do antigo assunto 246 do ClickDF.

Aplicado nos fluxos de cobrança e segunda cobrança.

---

## OS 39

O assunto 39 NÃO deve ser substituído globalmente.

Ele representa:

    SINAL ALTO

Portanto:

> 39 é um assunto legítimo do IXC e não deve ser usado como substituto de retirada.

Foi encontrado um fluxo de retirada acelerada que estava criando OS 39. Esse erro foi corrigido para OS 34.

---

# 7. FLUXOS CORRIGIDOS

## 7.1 Cobrança automática

A criação automática de cobrança passou a seguir:

    fatura
      ↓
    contrato
      ↓
    filial
      ↓
    OS 190

A criação grava `id_filial`.

Se a fatura não possuir contrato válido:

    NÃO CRIAR OS

---

# 8. RETIRADA SOLICITADA

O fluxo de retirada deve:

1. receber o cliente;
2. receber a fatura;
3. validar a fatura;
4. validar que a fatura pertence ao cliente;
5. obter `id_contrato`;
6. resolver a filial pelo contrato;
7. verificar se já existe OS 34 aberta;
8. criar OS 34 com a filial correta.

Não utilizar a filial atual do cliente como fonte da OS.

---

# 9. RETIRADA ACELERADA — NUNCA PAGOU

Foi identificado um erro importante no cron de monitoramento.

O fluxo antigo fazia:

    cliente
       ↓
    fatura
       ↓
    INSERT OS 39

Isso estava incorreto.

O fluxo corrigido é:

    cliente
       ↓
    fatura em aberto
       ↓
    id_contrato
       ↓
    resolver_filial_contrato()
       ↓
    abrir_os_retirada_ixc()
       ↓
    OS 34

A função:

    abrir_os_retirada_ixc()

passou a receber:

    id_cliente
    id_contrato
    mensagem

e determina a filial pelo contrato.

---

# 10. FUNÇÃO `abrir_os_retirada_ixc`

Local:

    app/bootstrap/cron_monitoramento.py

Responsabilidades:

- resolver filial pelo contrato;
- verificar OS 34 já existente;
- não duplicar OS;
- criar OS 34;
- gravar `id_filial`;
- retornar o ID da nova OS;
- registrar erro quando a criação não for possível.

Não existe fallback para filial 1.

---

# 11. MATERIAL RECOLHIDO

O fluxo "Material recolhido" possuía uma lógica problemática:

    cliente
       ↓
    procurar última OS 34
       ↓
    usar filial encontrada

Essa lógica não é segura porque a última OS histórica do cliente pode estar relacionada a outro contrato.

A regra corrigida passou a ser:

    fatura atual
       ↓
    contrato atual
       ↓
    filial do contrato
       ↓
    OS 171

Isso evita utilizar uma OS histórica de outro contrato como fonte da filial.

---

# 12. SEGUNDA COBRANÇA

Foi encontrada duplicidade de implementação de:

    count_segunda_cobranca()

Existiam duas definições diferentes.

Como uma definição posterior pode sobrescrever a anterior em Python, isso criava risco de comportamento inconsistente.

A implementação duplicada foi removida.

Também foi consolidado o fluxo de:

    mover_para_segunda_cobranca()

A segunda cobrança utiliza:

    OS 190

e não deve misturar o assunto 34.

A regra precisa permanecer consistente entre:

- contagem;
- listagem;
- movimentação;
- criação da OS;
- histórico.

---

# 13. CONSISTÊNCIA ENTRE `count_segunda_cobranca()` E `get_segunda_cobranca()`

Foi identificado um erro de consistência:

- `count_segunda_cobranca()` utilizava OS 190;
- `get_segunda_cobranca()` ainda filtrava OS 34.

Isso foi corrigido.

Regra:

> Todos os componentes do fluxo de segunda cobrança devem utilizar o mesmo assunto JACTOS: OS 190.

---

# 14. ENDPOINT LEGADO `/api/abrir-os`

Foi encontrado um endpoint antigo:

    /api/abrir-os

A auditoria verificou que não existiam referências ativas do frontend utilizando esse endpoint.

O endpoint legado foi removido para evitar:

- caminho alternativo de criação de OS;
- lógica duplicada;
- risco de utilizar regras antigas;
- dificuldade de auditoria.

A API oficial deve permanecer centralizada nos endpoints atualmente utilizados.

---

# 15. FUNÇÃO LEGADA DE RETIRADA

Também foi encontrada uma função antiga de abertura de retirada que recebia apenas:

    id_cliente

Essa abordagem não era suficiente para determinar corretamente a filial.

Após verificar que ela não possuía chamadas ativas, foi removida.

A regra atual exige contrato quando a filial da OS depende da cobrança.

---

# 16. AUDITORIA DOS `INSERT INTO su_oss_chamado`

Foi realizado levantamento de todos os pontos de criação direta de OS.

O objetivo foi localizar:

- assuntos errados;
- filiais fixas;
- criação sem contrato;
- caminhos duplicados;
- lógica legada;
- INSERTs fora da regra central.

Os principais pontos analisados envolveram:

    cron_auditoria_retiradas.py
    cron_auditoria.py
    cron_monitoramento.py
    router.py
    ixc_api.py
    service.py
    whatsapp_router.py

A regra aprendida é:

> Toda criação de OS deve ser rastreável até sua origem e possuir assunto e filial coerentes com o fluxo.

---

# 17. FILIAL DO OPERADOR NÃO É FILIAL DA OS

O sistema possui seleção de filial no ambiente operacional.

Essa seleção não deve ser confundida com a filial do contrato.

Usuários com nível adequado podem alternar a filial operacional para trabalhar em outras unidades.

Isso é comportamento intencional do negócio.

Portanto:

    filial do operador ≠ filial obrigatória da OS

Para OS vinculada à cobrança:

    filial da OS = filial do contrato

Não alterar a funcionalidade de troca de filial do operador.

---

# 18. EQUIPAMENTOS E RETIRADAS

Foi investigado o relacionamento entre:

    movimento_produtos
    patrimonio_movimentacao
    cliente_contrato

Descobertas importantes:

- `movimento_produtos` possui `id_contrato`;
- `movimento_produtos` possui `filial_id`;
- `movimento_produtos` possui `id_oss_chamado`;
- `patrimonio_movimentacao` possui `id_contrato`;
- a filial do patrimônio pode ser obtida através de `cliente_contrato`;
- `id_almoxarifado = 30` sozinho NÃO significa necessariamente que o equipamento já foi retirado;
- o histórico patrimonial deve ser considerado.

A identificação do equipamento deve priorizar o vínculo atual:

    contrato
       ↓
    patrimônio
       ↓
    última movimentação relevante

O almoxarifado é informação complementar, não substituto do vínculo contratual.

---

# 19. TESTES REALIZADOS

Foram realizados testes sem criação real de OS.

## Contrato → filial

Resultados:

    #26107 → filial 1
    #25448 → filial 3
    #7263  → filial 1

Contratos inválidos foram bloqueados.

---

## Fatura → contrato → filial

Foram validadas cadeias como:

    Fatura 566847
      Cliente 7156
      Contrato 7263
      Filial 1

    Fatura 578195
      Cliente 24659
      Contrato 26476
      Filial 3

    Fatura 577074
      Cliente 23212
      Contrato 24600
      Filial 3

    Fatura 577054
      Cliente 20245
      Contrato 25172
      Filial 2

Também foi encontrado caso real:

    Fatura 578071
      Cliente 22604
      Contrato 0

Resultado correto:

    BLOQUEADO

---

# 20. TESTE DE EQUIPAMENTO

Foram testados contratos reais somente em leitura.

Exemplos:

    contrato 26107
    filial 1
    patrimônio 5965

e:

    contrato 25448
    filial 3
    patrimônio 5943

Os testes confirmaram que o vínculo contrato → cliente → filial → equipamento podia ser recuperado sem realizar escrita.

---

# 21. HISTÓRICO DAS OS

O histórico passou a ser normalizado para diferenciar:

- contato;
- promessa;
- pagamento;
- segunda cobrança;
- retirada;
- WhatsApp;
- não atendeu;
- caixa postal.

Uma "Ligação realizada" com data de promessa não deve ser automaticamente classificada como uma nova promessa.

O campo de promessa deve representar uma promessa efetivamente registrada.

O resumo do histórico pode conter:

    quantidade_eventos
    teve_pagamento
    teve_promessa
    teve_segunda_cobranca
    quantidade_promessas
    quantidade_eventos_com_promessa
    quantidade_pagamentos
    quantidade_retiradas
    quantidade_contatos
    quantidade_nao_atendeu
    quantidade_caixa_postal
    quantidade_whatsapp
    ultima_acao
    ultima_data
    ultimo_operador

---

# 22. GERAÇÃO DA OS

O gerador de OS utiliza o contexto normalizado.

Arquivo:

    gerador_os.py

Funções públicas:

    gerar_os_cobranca()
    gerar_os_retirada()

O contexto pode incorporar:

    cliente
    contrato
    filial
    histórico
    resumo
    promessas
    situação de cobrança

A informação:

    2ª cobrança realizada: Sim

deve aparecer quando o resumo indicar essa situação.

---

# 23. IDENTIDADE JACTOS

Foram corrigidas referências de identidade que ainda apontavam para ClickDF/Cliquedf.

Exemplos corrigidos:

- nome do recebedor WhatsApp;
- descrição de OS de retirada;
- textos de serviço.

A identidade do sistema deve ser:

    JACTOS

Não utilizar ClickDF como identidade do fluxo atual.

---

# 24. LEGADO NÃO AGENDADO

Foi encontrada a existência de:

    app/bootstrap/corrigir_os_pendentes.py

Esse arquivo contém lógica antiga relacionada ao ClickDF e possuía filial fixa.

Foi verificado que não havia referência desse script em:

    /etc/cron*
    /var/spool/cron
    /etc/systemd/system
    /lib/systemd/system

Conclusão:

> O arquivo é legado e não está atualmente agendado.

Não alterar esse arquivo apenas por existir, sem necessidade operacional.

---

# 25. REGRA PARA LEGACY

Não fazer substituições globais cegas.

Especialmente:

    39

não deve ser globalmente substituído porque:

    39 = SINAL ALTO

Também não substituir números simplesmente porque aparecem em SQL.

Toda substituição deve ser contextual:

    assunto da OS
    endpoint
    criação
    consulta
    log
    variável
    documentação

---

# 26. MÉTODO DE ALTERAÇÃO APRENDIDO

Esta é uma das principais regras desta habilidade.

Nunca orientar edição manual linha por linha quando for possível automatizar com segurança.

O método correto é:

1. identificar o bloco exato;
2. capturar o conteúdo esperado;
3. exigir exatamente uma ocorrência;
4. abortar se houver zero ocorrências;
5. abortar se houver múltiplas ocorrências inesperadas;
6. substituir automaticamente;
7. validar sintaxe;
8. validar `git diff --check`;
9. revisar o diff;
10. só depois executar o próximo passo.

Padrão:

    old = """bloco exato"""
    new = """bloco corrigido"""

    count = text.count(old)

    if count != 1:
        abortar

    text.replace(old, new)

Nunca executar substituições cegas em todo o projeto.

---

# 27. VALIDAÇÃO OBRIGATÓRIA

Após alteração Python:

    python3 -m py_compile arquivo.py

Depois:

    git diff --check

Quando houver mudança de lógica de banco:

- realizar teste somente leitura;
- verificar resultado;
- confirmar que nenhuma escrita ocorreu.

Quando houver alteração de criação de OS:

- testar contrato válido;
- testar filial esperada;
- testar contrato inexistente;
- testar fatura sem contrato;
- confirmar que o caminho inválido não chama a API/INSERT.

---

# 28. NÃO REINICIAR O SERVIÇO PREMATURAMENTE

Durante uma correção que envolve múltiplos chamadores:

1. corrigir o código;
2. localizar todos os chamadores;
3. validar os fluxos;
4. verificar os INSERTs;
5. testar;
6. somente então considerar reinício/deploy.

Não reiniciar o Hub no meio de uma correção incompleta.

---

# 29. SEGREDOS

Durante a auditoria foram encontradas credenciais/token de Telegram hardcoded em arquivos.

Regra aprendida:

- não manter token diretamente no código;
- centralizar segredo em variável de ambiente/configuração segura;
- rotacionar token que tenha sido exposto;
- nunca incluir `.env` em documentação;
- nunca incluir senha de banco em habilidade ou backup público.

---

# 30. ESTADO FINAL ESPERADO

O HubCobrança JACTOS deve obedecer:

    COBRANÇA
       ↓
    Fatura
       ↓
    Contrato
       ↓
    Filial
       ↓
    OS 190

    RETIRADA
       ↓
    Fatura
       ↓
    Contrato
       ↓
    Filial
       ↓
    OS 34

    MATERIAL RECOLHIDO
       ↓
    Fatura
       ↓
    Contrato
       ↓
    Filial
       ↓
    OS 171

---

# 31. CHECKLIST PARA FUTURAS ALTERAÇÕES

Antes de alterar qualquer criação de OS:

[ ] Qual fluxo está criando a OS?

[ ] Qual é o assunto correto?

[ ] A OS depende de uma fatura?

[ ] Qual é o `id_contrato` da fatura?

[ ] O contrato existe?

[ ] O contrato possui `id_filial` válido?

[ ] O cliente da fatura corresponde ao cliente da operação?

[ ] Existe OS aberta que deve ser reutilizada?

[ ] Existe outro caminho que cria a mesma OS?

[ ] O código possui fallback para filial 1?

[ ] Existe algum assunto legado sendo usado?

[ ] O número 39 está sendo tratado corretamente como SINAL ALTO?

[ ] O fluxo cria a OS diretamente ou usa uma função central?

[ ] Existem outros chamadores?

[ ] O teste pode ser feito sem escrita?

[ ] `py_compile` passou?

[ ] `git diff --check` passou?

[ ] O diff foi revisado?

---

# 32. PRINCIPAL CONHECIMENTO ADQUIRIDO

O maior aprendizado desta auditoria é:

> Não basta corrigir o INSERT da OS. É necessário entender a origem dos dados que alimentam o INSERT.

Uma OS incorreta pode ser consequência de:

- fatura sem contrato;
- contrato errado;
- filial inferida do cliente;
- fallback para filial 1;
- assunto legado;
- função duplicada;
- endpoint antigo;
- cron diferente do fluxo web;
- histórico usado como fonte indevida;
- criação direta em banco;
- ausência de validação.

Portanto, a auditoria correta é feita em cadeia:

    origem
      ↓
    dados
      ↓
    contrato
      ↓
    filial
      ↓
    assunto
      ↓
    regra de negócio
      ↓
    criação da OS
      ↓
    histórico/log
      ↓
    validação

---

# 33. REGRA DE OURO

Para qualquer nova alteração no HubCobrança JACTOS:

> Primeiro entender o fluxo. Depois localizar todos os caminhos. Depois alterar cirurgicamente. Depois testar sem escrita. Depois revisar o diff. Só então fazer deploy.

E, para qualquer OS originada de cobrança:

> FATURA → CONTRATO → FILIAL → OS.

Nunca:

> CLIENTE → FILIAL PADRÃO → OS.

