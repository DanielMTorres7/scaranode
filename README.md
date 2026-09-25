# ScaraNode

<p align="center"><img src="docs/img/3d/placa-iso.png" width="640" alt="ScaraNode"></p>

Placa de nó de motor **Klipper** para braço SCARA: **RP2040-Zero** + **TMC2209** (NEMA 17) ou driver
externo **DM556** (NEMA 23). Face única, 76 × 64 mm, feita para fresar em casa.

| Projetista | Revisão | Data | Estado |
|---|---|---|---|
| Daniel M. Torres | v16 | 25/09/2026 | Validada: 128 pinos, DRC sem erro |

📘 **[Manual completo](docs/README.md)** · 📄 **[PDF](docs/ScaraNode-Manual-v16.pdf)** ·
🧾 **[Lista de materiais](docs/02-lista-de-materiais.md)** · 🔧 **[Montagem](docs/04-montagem.md)** ·
⚙️ **[Klipper](docs/07-firmware-klipper.md)**

## Estrutura

```
hardware/     placa KiCad (ScaraNode.kicad_pcb / .kicad_pro), a fonte editável
production/   arquivos para fabricar: gerber/, furação, BOM.csv
firmware/     configuração Klipper de referência
docs/         manual (Markdown + PDF), imagens, histórico de revisões
```

## Editar a placa

Abra `hardware/ScaraNode.kicad_pro` no **KiCad 10**. Ela usa só footprints da biblioteca padrão, além de
três footprints próprios embutidos no arquivo (soquetes do RP2040-Zero e do StepStick, jumper de fio).
Os comandos para regerar Gerber e furação estão em [docs/03-fabricacao.md](docs/03-fabricacao.md#arquivos-de-produção).

A placa original foi gerada e validada por uma ferramenta própria em Python, que não faz parte deste
repositório. O arquivo KiCad é completo e editável sem ela.

## Licença

Hardware sob **CERN-OHL-S-2.0** (ver [`LICENSE`](LICENSE)). Fotos de terceiros em `docs/img/componentes/`
mantêm as licenças listadas em [`CREDITOS.md`](docs/img/componentes/CREDITOS.md).

## Créditos

Modelos 3D das peças: bibliotecas oficiais do KiCad. Fotos de componentes: Wikimedia Commons, com
autores e licenças em [`docs/img/componentes/CREDITOS.md`](docs/img/componentes/CREDITOS.md).
