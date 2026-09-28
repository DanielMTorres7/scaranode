# 7. Firmware Klipper

Cada nó é um micro-controlador (`[mcu <nome>]`) do Klipper. O host fala com os quatro pelo USB, e os
pinos de cada nó levam o prefixo do nome (`j2:gpio4`).

Desde a v18 os dois drivers têm pinos próprios: um nó pode mover um motor no TMC2209 **e** outro no DM556 ao
mesmo tempo. Nesse caso, use o FIM1 (`gpio27`) para o eixo do TMC e o FIM2 (`gpio15`) para o do DM556: cada
chave fica no mesmo MCU que o seu motor, o que é o melhor para o homing.

## Gravar o Klipper no RP2040-Zero

No host, na pasta do Klipper:

```sh
make menuconfig
#   Micro-controller Architecture: Raspberry Pi RP2040/RP235x
#   Processor model: rp2040 · interface de comunicação: USB (padrão)
make
```

Primeira gravação: segure o botão **BOOT** do RP2040-Zero e conecte o USB. Ele aparece como um disco
(`RPI-RP2`): copie o `out/klipper.uf2` para lá, ou grave pelo host:

```sh
sudo service klipper stop
make flash FLASH_DEVICE=2e8a:0003   # RP2040 em modo BOOT (Klipper atual)
sudo service klipper start
```

Nas atualizações seguintes, com o nó já rodando o Klipper, `FLASH_DEVICE` pode ser o caminho
`/dev/serial/by-id/...` do nó.

Grave **um nó por vez** e anote o serial de cada um:

```sh
ls /dev/serial/by-id/
# usb-Klipper_rp2040_E6625C05E7xxxxxx-if00   ← cole no [mcu j2] serial:
```

Dica: etiquete cada placa (J1, J2, Z, J3) junto com o final do serial.

## Configuração

Referência completa, comentada: [`firmware/klipper/scaranode.cfg`](../firmware/klipper/scaranode.cfg).
Ela saiu da placa (pinagem conferida pino a pino), não do `printer.cfg` da máquina. O que depende da
mecânica e da cinemática SCARA está marcado com `# AJUSTAR`.

### Nó com TMC2209 (NEMA 17)

```ini
[mcu j2]
serial: /dev/serial/by-id/usb-Klipper_rp2040_XXXX-if00

[stepper_j2]
step_pin: j2:gpio4
dir_pin: j2:gpio5
enable_pin: !j2:gpio0          # EN ativo baixo
microsteps: 16                 # com UART vem daqui; em standalone é fixo em 1/16
gear_ratio: 6:1, 4:1
endstop_pin: !j2:gpio27        # chave NA para GND

[temperature_sensor motor_j2]
sensor_type: Generic 3950
sensor_pin: j2:gpio29
pullup_resistor: 100000
max_temp: 70

[gcode_button vm_sense_j2]
pin: j2:gpio1
press_gcode:
  G4 P0
release_gcode:
  M112
```

Com o **JU fechado** (recomendado), acrescente:

```ini
[tmc2209 stepper_j2]
uart_pin: j2:gpio2              # PDN_UART no pino 4 do soquete (v18)
uart_address: 3                # MS1 e MS2 fixos em 1 (R4/R5)
run_current: 1.0               # MÁXIMO 1,2 no StepStick
sense_resistor: 0.110
stealthchop_threshold: 0
```

### ⚠️ Para não queimar o driver

Um TMC2209 pegou fogo depois de rodar muito tempo a 1,7 A (27/09/2026). O que evita isso:

1. **`run_current` no máximo 1,0–1,2 A** no TMC2209. O StepStick não dissipa mais que isso, mesmo com ventoinha.
   O Klipper não impede um valor maior: o limite é seu. Motor que precisa de mais corrente vai no DM556.
2. **Use a UART.** Só com ela o Klipper lê os avisos de temperatura do TMC2209 (pré-aviso a ~120 °C, desligamento a
   ~143 °C) e para a máquina com erro. Em standalone, ninguém vigia o driver.
3. **Nunca ligue nem desligue o cabo do motor com a 24 V ligada.** A bobina gera um pico que mata o driver na hora,
   e nenhum componente da placa impede.
4. **Ponteira (terminal tubular) nos fios** dos plugues do motor (J6) e da 24 V (J5), bem apertados, e o plugue
   encaixado até o fim. Contato frouxo faz faísca.
5. **Fusível de 2 A só para esta placa** na caixa de fusíveis ([capítulo 6](06-circuitos.md#fusíveis-fora-da-placa)).
6. **Ventoinha no J7** sempre ligada, soprando o módulo.

### Nó com DM556 (NEMA 23)

```ini
[stepper_j1]
step_pin: !j1:gpio6            # pulso ativo baixo (ânodo comum)
dir_pin: j1:gpio7
enable_pin: j1:gpio8           # alto = habilitado, SEM !
step_pulse_duration: 0.000005
```

O `microsteps` do Klipper tem que ser igual ao configurado nas chaves do DM556.

## Tabela rápida de sinais

| Função | TMC2209 | DM556 |
|---|---|---|
| STEP | `gpio4` | `!gpio6` |
| DIR | `gpio5` | `gpio7` |
| Enable | `!gpio0` | `gpio8` |
| UART | `gpio2` (JU fechado) | — |
| NTC | `gpio29` (J3), pull-up 100000 | `gpio26` (J8) com dois motores na placa; `gpio29` com um |
| Fim de curso 1 / 2 | `!gpio27` / `!gpio15` (NA) | idem |
| Monitor 24 V | `gpio1` | idem |
