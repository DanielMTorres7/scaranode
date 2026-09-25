# 6. Circuitos e cálculos

A placa não tem esquema no editor de esquemas do KiCad: foi gerada por uma ferramenta própria em Python
(não publicada), que também guarda um esquema de referência escrito pino a pino, pela função de cada
pino no datasheet. Um validador compara esse esquema com cada ilha da placa: na v14 são **128 pinos conferidos, 0
divergências**. Os trechos abaixo seguem esse esquema.

## Entrada 24 V

```
J5 +24V ──►|── D1 1N5822 ──┬──────────┬──────────┬───────────┬─────────┬──► VMOT (U4.16)
            (anti-inversão) │          │          │           │         │
                          C10 470µF  D2 P6KE30A  J7 FAN     R12 10k   R9 47k ─► monitor
                            │          │ (TVS)    │           │
J5 GND ─────────────────────┴──────────┴──────────┴──── D3 LED ┘
```

O retorno de GND do borne vai por uma trilha própria de 2,5 mm até o C10, e dali ao pino 15 do TMC. É o
caminho dos pulsos do chopper (até ~1 A), que não deve depender dos raios finos do alívio térmico do plano.

| Grandeza | Valor | Comentário |
|---|---|---|
| VM no TMC | 23,6 V | 24 V menos ~0,45 V do D1. O TMC2209 aceita de 4,75 a 29 V. |
| Frenagem | ~0,04 J (estimativa: J2, 24:1, 250 mm/s) | O D1 impede a energia de voltar para a fonte. Com 470 µF, o VM sobe a ~27,4 V; com 100 µF chegava a ~30 V. |
| TVS P6KE30A | trabalha até 25,6 V, conduz a partir de 28,5 V | Segura surtos; não é proteção fina para o driver |
| LED | (23,6 − 2) / 10k ≈ 2,2 mA | Visível. R12 = 4k7 dá ~4,6 mA |
| Ventoinha | 24 V direto | Ventoinha brushless não precisa de diodo |

O fusível da 24 V fica na caixa de fusíveis central da máquina, não na placa.

## Monitor da 24 V

```
24V ── R9 47k ──┬── R11 10k ── GP1 (VSENSE)
                │
              R10 5k6   C6 100nF
                │         │
               GND       GND
```

- 23,6 × 5,6 / 52,6 = **2,51 V** no nó VSN com 24 V; 2,76 V com 26,4 V, ainda abaixo de 3,3 V.
- R11 limita a corrente pelo diodo interno do GP1 quando o RP está desligado e a 24 V presente.
- Abaixo do limiar de nível alto do RP2040, o botão "solta" e o Klipper executa o `release_gcode` (M112).

## Driver TMC2209

- VDD do módulo em 3,3 V (VCC_IO). **EN com pull-up de 10k (R6):** sem firmware rodando, o driver fica
  desligado.
- STEP e DIR chegam direto do RP (GP6, GP7).
- MS1/MS2/MS3 com pull-up de 10k (R4, R5, R7) e jumper ZM para GND.
- Pino 5 (PDN_UART) chega ao GP5 pelo JU. Pino 6 (CLK) fica aberto = clock interno.
- Módulo com RSENSE de 0,11 Ω: no cfg, `sense_resistor: 0.110`.
- **Corrente prática em StepStick: 1,0 a 1,2 A RMS, com ventoinha.** Acima disso o driver desarma por
  temperatura. Para 1,7 A, use driver externo pelo J4.

## Saída para driver externo (74ACT245)

```
            U2 74ACT245 (modo B→A: DIR=GND, OE#=GND, VCC=5V)
GP6 STP ─► B1 (18) ──► A1 (2) ─► J4.2 PUL−
GP7 DIR ─► B2 (17) ──► A2 (3) ─► J4.3 DIR−
GP8 ENA ─► B3 (16) ──► A3 (4) ─► J4.4 ENA−          J4.1 = 5V ─► PUL+ / DIR+ / ENA+
           B4–B8 (15–11) = GND
```

- Entradas TTL do ACT (nível alto ≥ 2,0 V) aceitam os 3,3 V do RP.
- Com PUL+/DIR+/ENA+ em 5 V, a saída em nível baixo acende o opto do DM556 (~14 mA; o 245 aguenta
  24 mA por saída).
- Pulso de STEP ativo baixo: `step_pin: !gpio6` e `step_pulse_duration: 0.000005` (o DM556 pede 2,5 µs).
- **ENA:** GP8 alto → A3 alto → opto apagado → motor **habilitado** (`enable_pin: gpio8`, sem `!`). Com o RP em
  reset ou em boot, o GP8 fica baixo e o DM556 fica desabilitado até o Klipper assumir.
- O DM556 é opticamente isolado, então não se forma laço de terra.

## NTC

```
3V3 ── R3 100k ──┬── GP29 (ADC3)
                 ├── C1 100nF ── GND
                 └── J3 ── NTC 100k ── GND
```

100k a 25 °C com pull-up de 100k dá 1,65 V; a 70 °C (~17,6k) dá ~0,49 V. O C1 filtra o ruído do cabo.

## Fins de curso

```
3V3 ── R13 10k ──┬── GP27        (FIM2: R14, R8, C5, GP15)
                 ├── C4 10nF ── GND
                 └── R2 1k ── J1 ── chave ── GND
```

Pull-up externo de 10k no lado do RP, 1k em série e 10 nF (RC de ~10 µs). Com a chave fechada, o pino fica
em 3,3 × 1/11 ≈ **0,30 V**. Por causa dos pull-ups externos (v14), o `^` no cfg é opcional.

## Pinos livres do RP2040

GP2, GP3, GP4, GP14, GP26 e GP28 não têm trilha. Servem para ligar por fio um ADXL345 (input shaping), com
`spi_software_*` no cfg; há um exemplo comentado em `firmware/klipper/scaranode.cfg`.
