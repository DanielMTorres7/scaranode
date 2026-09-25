# 7. Firmware Klipper

Cada nó é um micro-controlador (`[mcu <nome>]`) do Klipper. O host fala com os quatro pelo USB, e os
pinos de cada nó levam o prefixo do nome (`j2:gpio6`).

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
step_pin: j2:gpio6
dir_pin: j2:gpio7
enable_pin: !j2:gpio0          # EN ativo baixo
microsteps: 16                 # ZM aberto
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

Com o **JU fechado**, acrescente:

```ini
[tmc2209 stepper_j2]
uart_pin: j2:gpio5
uart_address: 3                # MS1 e MS2 abertos
run_current: 1.0
sense_resistor: 0.110
stealthchop_threshold: 0
```

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
| STEP | `gpio6` | `!gpio6` |
| DIR | `gpio7` | `gpio7` |
| Enable | `!gpio0` | `gpio8` |
| UART | `gpio5` (JU fechado) | — |
| NTC | `gpio29`, pull-up 100000 | idem |
| Fim de curso 1 / 2 | `!gpio27` / `!gpio15` (NA) | idem |
| Monitor 24 V | `gpio1` | idem |
