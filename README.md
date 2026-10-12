# Beyblade X — Parts Image Archive

Imágenes de **todas las partes de la generación Beyblade X** (Basic Line BX, Unique Line UX y Custom Line CX), organizadas con una convención de nombres consistente y un manifiesto legible por máquina.

- 📚 **Catálogo visual:** [`CATALOG.md`](CATALOG.md)
- 🧾 **Manifiesto (JSON):** [`manifest.json`](manifest.json) — nombre Takara Tomy, nombre Hasbro, abreviatura, línea, tipo, URL de origen, SHA-1, dimensiones.
- 🔄 **Actualización automática:** el workflow `Sync Beyblade X parts` corre cada lunes (y manualmente desde *Actions*) y agrega partes nuevas.

## Estructura

```
images/
├── bx-basic-line/
│   ├── blades/
│   │   ├── hasbro-debut/
│   │   ├── expand/
│   │   ├── x-over/
│   │   └── collab/<marca>/        (marvel, star-wars, transformers, jurassic-world…)
│   ├── ratchets/
│   └── bits/
├── ux-unique-line/
│   ├── blades/ (+ hasbro-debut/)
│   ├── ratchet-integrated-blades/
│   ├── ratchets/
│   └── bits/
└── cx-custom-line/
    ├── lock-chips/
    ├── main-blades/
    ├── metal-blades/
    ├── over-blades/
    ├── assist-blades/
    ├── ratchets/
    ├── ratchet-integrated-bits/
    └── bits/
```

## Convención de nombres

```
<línea>-<tipo>-<parte>[--<variante>][--combo].<ext>
```

| Segmento | Regla | Ejemplos |
|---|---|---|
| `línea` | `bx` · `ux` · `cx` | `bx` |
| `tipo` | tipo de parte en singular, kebab-case | `blade`, `ratchet`, `bit`, `lock-chip`, `main-blade`, `assist-blade`, `metal-blade`, `over-blade`, `ratchet-integrated-blade`, `ratchet-integrated-bit` |
| `parte` | **Blades/CX:** nombre Takara Tomy en kebab-case (Hasbro si no existe TT). **Ratchets:** código `n-nn`. **Bits / Assist Blades:** `abreviatura-nombre`. **Collabs:** `marca-nombre`. | `dran-sword`, `3-60`, `gf-gear-flat`, `k-knuckle`, `marvel-iron-man` |
| `--variante` | modo/forma alterna de la misma parte | `--upper-mode`, `--smash-mode`, `--rapid-hit-type` |
| `--combo` | la imagen muestra el Bey armado, no la parte aislada | `bx-blade-clamp-crab--combo.jpg` |
| `ext` | formato **original** de la wiki, sin re-codificar (`png` o `jpg`) | |

Ejemplos reales:

```
images/bx-basic-line/blades/bx-blade-dran-sword.png
images/bx-basic-line/ratchets/bx-ratchet-3-60.png
images/bx-basic-line/bits/bx-bit-gf-gear-flat.png
images/ux-unique-line/bits/ux-bit-ra-rubber-accel.png
images/cx-custom-line/main-blades/cx-main-blade-eclipse--upper-mode.png
images/bx-basic-line/blades/collab/marvel/bx-blade-marvel-iron-man--combo.jpg
```

Reglas: todo en minúsculas ASCII, separador `-`, doble guion `--` sólo para modificadores. Los nombres son deterministas, así que la misma parte siempre produce la misma ruta.

## Integridad

Cada archivo se descarga en su versión original (`format=original`) y se verifica contra el **SHA-1** publicado por la API de MediaWiki antes de escribirse. El campo `integrity` de `manifest.json` indica el resultado:

- `exact`: los bytes son idénticos al original subido a la wiki.
- `cdn-modified`: el CDN de Fandom entrega el archivo sin algunos metadatos (pasa con subidas antiguas, sobre todo JPG). Se acepta sólo si el formato coincide y el tamaño difiere menos de 5%. Se registra su SHA-1 real en `sha1_stored`.

El script nunca borra archivos: sólo reporta los huérfanos.

## Uso local

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/sync_parts.py --dry-run   # sólo muestra el plan
.venv/bin/python scripts/sync_parts.py             # descarga y actualiza
```

## Créditos y aviso legal

- Imágenes y datos obtenidos de la [Beyblade Wiki (Fandom)](https://beyblade.fandom.com): [Basic Line](https://beyblade.fandom.com/wiki/List_of_Basic_Line_parts) · [Unique Line](https://beyblade.fandom.com/wiki/List_of_Unique_Line_parts) · [Custom Line](https://beyblade.fandom.com/wiki/List_of_Custom_Line_parts). El texto de la wiki está bajo CC BY-SA.
- **Beyblade** y todos los diseños de producto son marcas registradas y propiedad de © Takara Tomy / Hasbro / Aoki Takafumi. Este es un proyecto de fans **sin fines de lucro** y sin afiliación con ninguno de ellos.
- Si eres titular de los derechos y quieres que retire algún contenido, abre un *issue* y lo quitaré.
- El código (`scripts/`, workflow) se publica bajo licencia MIT.
