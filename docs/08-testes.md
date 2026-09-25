# 8. Primeira ligação e testes

Faça na ordem. Cada passo só começa se o anterior deu o resultado esperado. Antes de tudo, faça a
[conferência sem energia](04-montagem.md#conferência-antes-de-energizar).

## Roteiro

| Passo | O que fazer | O que esperar |
|:-:|---|---|
| 1 | Só o USB, sem 24 V, sem o módulo TMC | O LED do RP acende. Grave o Klipper ([cap. 7](07-firmware-klipper.md)); o nó aparece em `/dev/serial/by-id/`. |
| 2 | Meça o pino VDD do soquete do TMC e o pino 20 do U2 | 3,3 V e 5,0 V |
| 3 | Ligue a 24 V, ainda sem o módulo | D3 acende. ~23,6 V no VMOT do soquete e ~2,5 V no GP1. |
| 4 | Desligue tudo. Encaixe o TMC, ajuste o trimpot para ~1 A, religue o USB e depois a 24 V | Nada esquenta em repouso |
| 5 | `STEPPER_BUZZ STEPPER=stepper_j2` | O motor vibra 1 mm para um lado e para o outro. Se não vibrar, confira o EN e as bobinas no J6. |
| 6 | Um `G1` curto, depois um quadrado lento | Lados retos e tamanho certo. Curvo ou errado: confira `gear_ratio`, micropasso ou `dir_pin`. |
| 7 | `QUERY_ENDSTOPS` com a chave solta e apertada | `open` → `TRIGGERED`. Se inverter, troque o `!` do `endstop_pin`. |
| 8 | Leia a temperatura do `motor_j2` | Temperatura ambiente (±3 °C). Muito alta ou muito baixa: confira o `pullup_resistor: 100000`. |
| 9 | Nó DM556: mesmo roteiro | Se perder posição a cada inversão, tire o `!` do `step_pin`. Motor sem torque: confira o ENA (`gpio8`, sem `!`). |
| 10 | Corte a 24 V com o Klipper rodando | O Klipper entra em M112 (`release_gcode` do `vm_sense`). `FIRMWARE_RESTART` para voltar. |
| 11 | Feche o JU e ative a seção `[tmc2209]` | `DUMP_TMC STEPPER=stepper_j2` responde; o trimpot passa a ser ignorado. |

## Diagnóstico

| Sintoma | Causa provável | Onde olhar |
|---|---|---|
| Nada liga com 24 V, D3 apagado | 24 V invertido (o D1 bloqueia) ou D1 soldado ao contrário | Polaridade do J5; faixa do D1 à esquerda |
| Fonte entra em proteção ao ligar a 24 V | D2 (TVS) soldado ao contrário | Faixa do D2 à esquerda |
| Klipper não acha o nó | Cabo USB só de carga, ou firmware não gravado | `lsusb`, `ls /dev/serial/by-id/` |
| Motor não segura (TMC) | EN em alto: Klipper não habilitou, ou R6 em curto | `enable_pin: !gpio0` |
| Motor vibra mas não gira | Um par de bobinas trocado no J6 | Meça a resistência: pares de ~1–3 Ω |
| Motor gira ao contrário | Sentido da bobina | `!` no `dir_pin` ou inverta um par |
| Fim de curso sempre acionado | JP1 faltando (sem GND) ou chave NF sem `!` ajustado | Continuidade GND J1 × J5 |
| NTC marca −273 °C ou valor absurdo | NTC aberto, sem JP1, ou `pullup_resistor` errado | J3, JP1 |
| TMC desarma depois de minutos | Corrente acima de ~1,2 A RMS ou sem ventoinha | Trimpot / `run_current`, J7 |
| `DUMP_TMC` sem resposta | JU aberto, pino 5 do módulo não é PDN_UART, ou MS3 fechado | [Jumpers](05-conectores-e-jumpers.md#jumpers) |
| DM556 não se move | J4 invertido, ou ENA desabilitando | Ordem 5V, PUL−, DIR−, ENA−; `enable_pin: gpio8` |
| M112 aleatório | Queda da 24 V, ou mau contato no J5 | Aperto do borne; fonte |

## O que a placa não faz

- **Entrada de 5 V separada.** A lógica é alimentada pelo USB, que precisa estar ligado de qualquer
  jeito (é o canal de dados do Klipper). Um borne de 5 V extra só criaria o risco de alimentar a porta
  USB do host por trás.
- **Homing sem sensor (StallGuard).** Precisa do pino DIAG do TMC2209, que o módulo StepStick usado não
  expõe. Além disso, o StallGuard atrás de planetária 6:1 + correia 4:1 é pouco confiável. O homing é
  por chave, no J1/J2.
- **Corrente acima de 1,2 A RMS no soquete.** O StepStick não dissipa. Use driver externo pelo J4.
- **Encoder ou realimentação de posição.** O sistema é malha aberta, como todo Klipper.
- **Drivers SPI (TMC2130, TMC5160).** Os pinos 2–4 do soquete estão nos pull-ups de micropasso, sem SPI.
- **Conector para ADXL345.** Não há. Para input shaping, ligue por fio em GP2/GP3/GP4 + um CS livre
  ([exemplo no cfg](../firmware/klipper/scaranode.cfg)).
