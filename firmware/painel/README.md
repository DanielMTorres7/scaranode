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

## Gravar o firmware

A placa precisa de **MicroPython** no RP2040-Zero (segure BOOT, ligue a USB e copie o `.uf2` do
[micropython.org](https://micropython.org/download/RPI_PICO/) para o drive `RPI-RP2`).
Depois, no painel, em **Registro › Firmware da placa**:

1. escolha a **revisão da placa** (v14–v17 ou v18): ela vai num `placa.py` (`REV = "v17"`) e decide os pinos;
2. clique em **Gravar firmware do site**.

O painel solta o motor, para o firmware e grava `main.py`, `no.py` e `placa.py` pelo raw REPL (como o
`mpremote`). Cada arquivo vai para um `.tmp`, é conferido (tamanho e SHA-256) e só então substitui o
antigo: se algo falhar no meio, a placa continua com o firmware anterior.

## Pinos por revisão

| | v14–v17 | v18 |
|---|---|---|
| STEP / DIR do TMC2209 | GP6 / GP7 (compartilhados) | GP4 / GP5 |
| STEP / DIR do DM556 | GP6 / GP7 (compartilhados) | GP6 / GP7 |
| UART do TMC2209 | GP5 | GP2 |
| Modo "Ambos" (mesmos pulsos nos dois drivers) | sim | não |

Comuns: EN do TMC GP0, 24 V GP1, ENA do DM556 GP8, FIM1 GP27, FIM2 GP15, NTC GP29, LED GP16.
Revisão nova: uma linha na tabela `PLACAS` do `no.py` e uma opção no seletor do `index.html`.

## Publicar uma versão nova

Edite `no.py` (suba `FW = "painel 1.x"`) e dê push em `main`: o workflow `.github/workflows/painel.yml`
publica no GitHub Pages. Quem abrir o painel vê "diferente do site" ao conectar e grava com um clique.
