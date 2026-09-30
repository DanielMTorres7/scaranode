# Painel web do ScaraNode

Painel de bancada para testar a placa sem Klipper: move o motor, configura o TMC2209 ou o DM556, lê fins de
curso, NTC e 24 V, e grava o próprio firmware na placa.

**Abrir:** <https://danielmtorres7.github.io/scaranode/> no **Chrome ou Edge** (computador). A página usa
Web Serial: a conexão vai direto do navegador para a placa ligada na USB do seu computador, sem passar
por servidor nenhum.

| Arquivo | O que é |
|---|---|
| `index.html` | o painel (arquivo único, sem dependências) |
| `no.py` | firmware MicroPython: servidor JSON pela USB, passos pela PIO + DMA |
| `main.py` | boot: deixa os drivers soltos e chama `no.rodar()` |
| `robo.html` | robô: várias placas ao mesmo tempo (J1, J2, Z), referência e desenho de SVG |

## Gravar o firmware

A placa precisa de **MicroPython** no RP2040-Zero (segure BOOT, ligue a USB e copie o `.uf2` do
[micropython.org](https://micropython.org/download/RPI_PICO/) para o drive `RPI-RP2`).
Depois, no painel, na aba **Firmware**:

1. escolha a **revisão da placa** (v14–v17 ou v18): ela vai num `placa.py` (`REV = "v17"`) e decide os pinos;
2. clique em **Gravar firmware do site**.

O painel solta o motor, para o firmware e grava `main.py`, `no.py` e `placa.py` pelo raw REPL (como o
`mpremote`). Cada arquivo vai para um `.tmp`, é conferido (tamanho e SHA-256) e só então substitui o
antigo: se algo falhar no meio, a placa continua com o firmware anterior.

## Editar o firmware

Na aba **Firmware**, **Editar o firmware**: baixe `no.py`, `main.py` e `placa.py`, edite no seu editor e grave com
**Gravar arquivos do computador…** (um ou mais `.py`; só os escolhidos são trocados). Para voltar à versão
publicada, **Gravar firmware do site**. Para publicar a sua versão para todos, faça o commit aqui (veja abaixo).

## Pinos por revisão

| | v14–v17 | v18 |
|---|---|---|
| STEP / DIR do TMC2209 | GP6 / GP7 (compartilhados) | GP4 / GP5 |
| STEP / DIR do DM556 | GP6 / GP7 (compartilhados) | GP6 / GP7 |
| UART do TMC2209 | GP5 | GP2 |
| Modo "Ambos" (mesmos pulsos nos dois drivers) | sim | não |

Comuns: EN do TMC GP0, 24 V GP1, ENA do DM556 GP8, FIM1 GP27, FIM2 GP15, NTC GP29, LED GP16.
Revisão nova: uma linha na tabela `PLACAS` do `no.py` e uma opção no seletor do `index.html`.

## Robô (várias placas)

**Abrir:** <https://danielmtorres7.github.io/scaranode/robo.html> (ou o botão **Robô** no painel). Uma conexão
por placa: **Adicionar placa** para cada uma; na próxima vez o navegador reconecta sozinho.

- **Eixos:** cada eixo (J1, J2, Z) diz em que placa e em que driver está ligado, a redução (ou o avanço do fuso),
  o sentido, os limites, a velocidade e como é referenciado (manual ou por fim de curso). J1 e J2 precisam estar
  na mesma placa v18, um no TMC2209 e o outro no DM556: a placa entra no modo **dois**.
- **Tudo fica salvo na placa** (`config.json`, comando `salva`): driver, correntes, fins de curso e os eixos
  ligados nela; o comprimento do braço vai com o J1 e as alturas da caneta com o Z. A placa já liga
  configurada (motores soltos) e o painel lê tudo de volta ao conectar, em qualquer computador.
- **Firmware:** na aba **Placas**, cada placa mostra a versão dela e a do site; **Atualizar** grava a última
  versão com a revisão que a própria placa informa (v17 ou v18). O `config.json` não é tocado.
- **Desenho:** formas prontas ou um arquivo SVG (linhas, curvas, retângulos, círculos; texto precisa virar
  curva), posição e tamanho na área de trabalho, velocidade. **Simular** mostra o movimento sem mexer nos
  motores; **Desenhar** manda a trajetória.

Como a trajetória anda: o painel faz a cinemática inversa e planeja a velocidade (reduz nos cantos e onde as
juntas ficariam rápidas demais), divide em segmentos de 10 ms e manda os passos de cada segmento para a placa
(`tjini`/`tj`). Na placa, cada canal tem a sua SM da PIO lendo um anel de 512 segmentos por DMA; as duas partem
no mesmo ciclo e o painel acerta os atrasos para os dois canais não se afastarem mais que ~1 µs. Se a USB
atrasar e os dados acabarem, a SM para no fim do que chegou e a posição continua exata.

O painel de uma placa troca o modo do driver para o que estiver escolhido nele: depois de usá-lo numa placa do
robô, reinicie a placa (ela volta ao que está no `config.json`).

## Publicar uma versão nova

Edite `no.py` (suba `FW = "painel 1.x"`) e dê push em `main`: o workflow `.github/workflows/painel.yml`
publica no GitHub Pages. Quem abrir o painel vê "diferente do site" ao conectar e grava com um clique.
