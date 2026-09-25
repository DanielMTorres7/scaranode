# Histórico de revisões

Projetista: **Daniel M. Torres**.

| Rev. | Data | Resumo |
|---|---|---|
| v17 | 25/09/2026 | Esquemático KiCad publicado (ERC e paridade com a placa); 13 resistores iguais de 1/4 W; R13 e R14 inclinados a 50° com o GND do RP ligado direto ao plano; coluna da esquerda com folgas iguais; GND contínuo sem o jumper de fio JP1; faixas de cor nos renders |
| v16 | 25/09/2026 | Placa 76 × 64 mm com furos M3 alinhados + DXF mecânico; U2 em soquete DIP-20; borne do motor KF128 azul; NTC separado dos fins de curso; LED de 5 mm |
| v15 | 25/09/2026 | Conectores de sinal passam a JST XH 2,5 mm (as peças reais); 74ACT245 soldado direto; borne da 24 V verde e do motor azul |
| v14 | 25/09/2026 | ENA do DM556 no GP8 (J4 passa a 4 vias); pull-ups de 10k R13/R14 nos fins de curso. Manual e repositório publicados. |
| v13 | 25/09/2026 | Só duas brocas (1,0 e 1,6 mm) + M3 |
| v12 | 25/09/2026 | C10 = 470 µF 35 V; placa passa a 75,8 × 64 mm |
| v11 | 24/09/2026 | Jumper JU: UART do TMC2209 no GP5 |
| v10 | 24/09/2026 | LED D3 na borda; trilha de retorno de GND do borne |
| v9 | 24/09/2026 | Anel dos conectores KK corrigido (0,40 mm); primeiros Gerbers |
| v1–v8 | 24/09/2026 | Layout inicial, regras de fresa, pinagem do RP2040 |

## v17 — esquemático e resistores iguais

- **Esquemático** em `hardware/ScaraNode.kicad_sch` e em [PDF](ScaraNode-Esquematico-v17.pdf): uma folha, blocos
  por função, rótulos na ponta dos pinos. ERC sem erro nem aviso; paridade placa × esquemático sem divergência.
  Símbolos próprios em `hardware/ScaraNode.kicad_sym`, footprints próprios em `hardware/ScaraNode.pretty`.
- Pinos livres ganham na placa a rede `unconnected-(…)` que o esquemático gera; o cobre não muda.
- **R13 e R14 passam a 1/4 W, furos a 10,16 mm** (antes 1/8 W a 7,62): os 13 resistores são iguais. Continuam
  embaixo do RP2040-Zero.
- Coluna da esquerda (XH, R2/R3/R8, C1/C4/C5, barra fêmea do RP) com folgas iguais entre corpos: ~0,9 mm do XH à
  perna do R e da perna do R ao capacitor (medidas com perna de 0,8 mm, acima da real), ~1,0 mm do capacitor à
  barra fêmea. O capacitor para no limite da isolação de 0,6 mm com as ilhas livres do RP.
- As exceções de courtyard deixam de ser uma lista fixa: onde os courtyards se sobrepõem ou os corpos ficam a menos
  de 2 mm, a folga real entre os corpos (desenho de fabricação, pernas pelo furo) tem que ser ≥ 0,10 mm. Menor
  folga: 0,30 mm (J7 × cabeça do M3 do H1). O DRC do KiCad continua marcando 13 sobreposições de courtyard como
  erro; são essas, conferidas pela folga real.
- **Sem jumper de fio**: o U2 (74ACT245), o C2 e a trilha de 5 V que chega a eles descem 1 mm; o J4 fica onde
  estava. O plano de GND passa a chegar à coluna da esquerda (NTC e fins de curso) entre o último pino do
  RP2040-Zero e a trilha de 5 V, e o JP1 (fio de GND por cima da trilha de 5 V) sai da placa, da lista de
  materiais e da montagem. O J4 fica a
  ~0,5 mm do soquete do U2; o U2 se afasta do RP (~1,7 mm).
- **R13 e R14 inclinados a 50°, paralelos**: a ilha do fim de curso fica na altura do GP27/GP15 (trilhas retas) e a
  ilha de 3V3 dos dois cai na mesma trilha de 3V3, que agora desce a ~9,4 mm da fileira esquerda do RP (antes
  descia a 3,2 mm). Com isso o **GND do RP2040-Zero liga direto ao plano de GND de cima** por um canal de
  ~6 mm. O R6 passa um pouco para a direita (1,3 mm) e o EN chega a ele em L, sem ilha de cobre solta a mais.
  Folgas: R13 × R14, R13 × R6 e R14 × R6 ~0,8 mm; R13/R14 a ~1,2 mm da barra fêmea; R6 a ~0,9 mm da barra da
  direita.
- Renders com as faixas de cor de cada resistor.
- Validado: 126 pinos, ERC 0, paridade 0, 0 violações de cobre, 0 ligações faltando. Furação: 118 × 1,0 ·
  8 × 1,6 · 4 × 3,2.

## v16 — dimensões redondas, soquete DIP e DXF

- Contorno passa de 75,8 × 64 para **76 × 64 mm** (borda direita +0,2 mm).
- Furos M3 a 3,5 mm das bordas: H1/H3/H4 num retângulo de 69 × 57 mm; H2 na coluna do H4, 18 mm abaixo da borda
  de cima. Antes: H1 e H3 desalinhados 0,2 mm, cotas quebradas.
- U2 com footprint de **soquete DIP-20** (mesmos furos, corpo maior). Exceção medida: o corpo do soquete termina
  a ~1 mm da perna do R7.
- `production/ScaraNode-mecanico.dxf`: contorno, furos e cotas.
- Coluna da esquerda reorganizada: **NTC (J3) sozinho em cima** e os **dois fins de curso (J1, J2) juntos**
  mais abaixo, com um vão de ~9 mm entre os grupos. O J2 fica no limite da trilha de 5 V (y = 41,2).
- **LED de 5 mm** (mesmo passo de 2,54 mm e furo de 1,0 mm do de 3 mm); o R12 subiu 1 mm para ele caber.
  Folgas medidas: LED a ~0,7 mm do J3; J1 a ~1,6 mm da perna do R8.
- Validado: 128 pinos, 0 violações de cobre, 0 ligações faltando.

## v15 — conectores JST XH

- J1, J2, J3, J4 e J7 trocam o footprint Molex KK (2,54 mm) pelo **JST XH** (B2B/B4B-XH-A, 2,5 mm), que é o
  conector usado de fato. As ilhas continuam ovais de 1,8 × 2,4 mm com furo de 1,0 mm.
- J4: as trilhas do 74ACT245 (passo 2,54) fazem um desvio curto até os pinos do XH (passo 2,5).
- O corpo do XH é mais largo que o do KK. Exceções de courtyard aceitas, com as medidas do F.Fab:
  J1/J2/J3 × R2/R3/R8 (plástico a ~0,2 mm da perna do resistor, sem cobre no meio) e J7 × H1/D2 (~1 mm da
  cabeça do M3, ~1,5 mm da perna do D2). Afastar a coluna para a esquerda violaria a isolação da trilha de 5 V.
- U2 soldado direto (sem soquete DIP). Borne J5 verde (24 V), J6 azul (motor).
- Validado: 128 pinos, 0 violações de cobre, 0 ligações faltando. Furação igual: 120 × 1,0 · 8 × 1,6 · 4 × 3,2.

## v14 — ENA do DM556 e pull-ups dos fins de curso

- **ENA:** GP8 → B3 do 74ACT245 (pino 16, antes em GND) → A3 (pino 4) → J4.4. O J4 passa a KF2510 de
  4 vias: 5V, PUL−, DIR−, ENA−, com o ENA+ do DM556 no 5 V como PUL+/DIR+. GP8 alto = motor habilitado
  (`enable_pin: gpio8`, sem `!`). Com o RP em reset ou em boot, o GP8 fica baixo e o DM556 fica
  desabilitado até o Klipper assumir.
- **Pull-ups de 10k** R13 (GP27/FIM1) e R14 (GP15/FIM2) do lado do RP, embaixo do módulo. São de 1/8 W
  (DIN0204, furos a 7,62 mm), porque o de 1/4 W encostava no soquete. O R14 fica inclinado 60°.
- Exceção de DRC aceita: o canto do courtyard do R14 invade ~0,2 mm o do soquete do RP. A ilha fica a
  0,68 mm do plástico.
- Validado: 128 pinos, 0 violações de cobre, 0 ligações faltando.

## v13 — só duas brocas

- Furos ≤ 1,2 mm viram 1,0 mm; entre 1,2 e 3,0 mm viram 1,6 mm; 3,2 mm (M3) fica. As ilhas cresceram onde
  foi preciso para manter o anel ≥ 0,4 mm.
- Pinos 1 e 19 do U2 com ligação sólida ao plano (não cabia o alívio térmico).

## v12 — C10 de 470 µF

- C10 = 470 µF 35 V (Ø10 mm, passo 5 mm), para absorver a energia de frenagem com o D1 em série.
  Com 470 µF, o VM sobe a ~27,4 V na frenagem estimada; com 100 µF chegava a ~30 V.
- A faixa de 24 V inteira subiu 4 mm para o capacitor caber; a placa passou a 75,8 × 64 mm.

## v11 — jumper de UART

- JU (1x2) entre o RP e o TMC: JU.2 ← GP5, JU.1 → pino 5 do StepStick (PDN_UART). Aberto = standalone.
- Sem resistor e sem pull-up: UART de 1 fio half-duplex.
- Os pinos 5–6 do soquete não ficam mais livres para o curto RST/SLP de A4988/DRV8825.

## v10 — LED na borda e retorno de GND

- D3 na borda esquerda, abaixo do R12.
- Trilha de GND de 2,5 mm do borne J5 até o C10 e dali ao pino 15 do TMC: caminho sólido para os pulsos do
  chopper, sem depender dos raios do alívio térmico.

## v9 — pronta para fresar

- Conectores KK com ilha oval de 1,8 × 2,4 mm e furo de 1,0 mm (anel de 0,40 mm; a biblioteca deixava
  0,28 mm).
- Menor vão entre redes: 0,601 mm. Menor anel: 0,40 mm.
- Primeiros Gerbers e a regra de espelhamento para fresar com o cobre para cima.

## Decisões de projeto que valem para todas as revisões

- **Fresa desconhecida → regras seguras:** isolação de 0,6 mm, sinal de 1,2 mm, ilhas generosas.
- **Ilhas de cobre soltas são mantidas:** sobra menos cobre para a fresa tirar.
- **Sem entrada de 5 V:** o USB é obrigatório para o Klipper e já alimenta a lógica.
- **Pino 6 (CLK) do StepStick livre:** aterrar sem medir o módulo pode danificar variantes que usam esse
  pino para outra coisa.
- **Sem homing sensorless:** o módulo usado não expõe o DIAG; o homing é por chave (J1/J2).
- **Fusível da 24 V** fica na caixa de fusíveis central da máquina.
- **LED:** R12 = 10k (~2,2 mA). Para mais brilho, R12 = 4k7 (~4,6 mA).
