#!/usr/bin/env python3
# make_icon.py by Daniele Lolli (UncleDan) feat. Claude AI - Release 2.0b1 - 2026-11-09 17-29-12
#
# MameCommander - Copyright (c) 2026 Daniele Lolli
# Licenza MIT: vedi il file LICENSE.
#
# SPDX-License-Identifier: MIT
#
# MameCommander e' un programma di utilita' non affiliato al progetto
# MAME. Ogni merito dell'emulazione va al team di sviluppo di MAME.
#
"""
Generatore dell'icona di MameCommander.

Produce:
  ../MameCommander.ico   icona multi-risoluzione per l'eseguibile Windows
  ../MameCommander.png   icona 256x256 per la voce di menu su Linux

Uso:
    python3 build/make_icon.py

Richiede Pillow (pip install pillow). Serve solo per RIGENERARE l'icona:
i file prodotti sono gia' inclusi nel progetto, quindi per compilare
MameCommander non e' necessario avere Pillow installato.

NOTA SUL DISEGNO
Ogni dimensione viene disegnata NATIVAMENTE, non ridimensionando la piu'
grande. Rimpicciolire un disegno dettagliato a 16x16 produce una poltiglia
sfocata: a quella dimensione servono forme piu' grosse, meno elementi e
niente dettagli sottili. Per questo il livello di dettaglio cresce con la
dimensione (la cornice interna e la fessura della base compaiono solo
dalle icone medie in su).

Il soggetto e' un joystick arcade su fondo blu con cornice ciano, gli
stessi colori dell'interfaccia del programma.
"""

import io
import struct

from PIL import Image, ImageDraw

# Colori: gli stessi dell'interfaccia curses, cosi' icona e programma
# si riconoscono come la stessa cosa.
BLU_FONDO = (0, 0, 170)
BLU_SCURO = (0, 0, 120)
CIANO = (85, 255, 255)
ROSSO_PALLA = (220, 50, 50)
ROSSO_LUCE = (255, 130, 130)
GRIGIO_ASTA = (200, 200, 210)
GRIGIO_OMBRA = (120, 120, 135)
NERO_BASE = (25, 25, 35)
GIALLO = (255, 200, 40)

DIMENSIONI = [16, 24, 32, 48, 64, 128, 256]


def disegna(size: int) -> Image.Image:
    """Disegna l'icona alla dimensione richiesta.

    Si lavora con un fattore di scala 4x e si riduce alla fine: cosi' i
    bordi curvi risultano morbidi (antialiasing) senza dover disegnare a
    mano ogni pixel. Le PROPORZIONI restano decise qui in base a `size`,
    quindi il disegno resta adatto alla dimensione finale.
    """
    s = 4
    d = size * s
    img = Image.new("RGBA", (d, d), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)

    piccola = size <= 24
    media = size <= 48

    # --- Fondo: quadrato con angoli arrotondati -----------------------
    raggio = int(d * (0.14 if piccola else 0.18))
    margine = int(d * 0.02)
    dr.rounded_rectangle(
        [margine, margine, d - margine - 1, d - margine - 1],
        radius=raggio,
        fill=BLU_FONDO,
        outline=CIANO,
        width=max(s, int(d * (0.045 if piccola else 0.040))),
    )

    # Cornice interna sottile: un richiamo ai bordi di Norton Commander.
    # Alle dimensioni piccole si perderebbe, quindi si omette.
    if not media:
        inset = int(d * 0.11)
        dr.rounded_rectangle(
            [inset, inset, d - inset - 1, d - inset - 1],
            radius=int(raggio * 0.6),
            outline=BLU_SCURO,
            width=max(1, int(d * 0.012)),
        )

    # --- Base del joystick --------------------------------------------
    # Il joystick non e' centrato ma spostato a sinistra: i pulsanti
    # occupano la meta' destra, e con il joystick al centro finirebbero
    # schiacciati contro il bordo.
    base_w = d * (0.50 if piccola else 0.46)
    base_h = d * (0.16 if piccola else 0.14)
    base_cx = d * (0.40 if piccola else 0.42)
    base_cy = d * 0.73
    dr.rounded_rectangle(
        [base_cx - base_w / 2, base_cy - base_h / 2,
         base_cx + base_w / 2, base_cy + base_h / 2],
        radius=int(base_h * 0.45),
        fill=NERO_BASE,
    )
    # Fessura chiara sulla base: da' profondita', ma solo dove si vede.
    if not media:
        dr.rounded_rectangle(
            [base_cx - base_w * 0.36, base_cy - base_h * 0.12,
             base_cx + base_w * 0.36, base_cy + base_h * 0.10],
            radius=int(base_h * 0.12),
            fill=GRIGIO_OMBRA,
        )

    # --- Asta -----------------------------------------------------------
    asta_w = d * (0.11 if piccola else 0.09)
    asta_top = d * (0.42 if piccola else 0.40)
    dr.rounded_rectangle(
        [base_cx - asta_w / 2, asta_top, base_cx + asta_w / 2, base_cy],
        radius=int(asta_w * 0.5),
        fill=GRIGIO_ASTA,
    )
    # Lato in ombra: rende l'asta cilindrica invece che piatta.
    if not piccola:
        dr.rounded_rectangle(
            [base_cx + asta_w * 0.05, asta_top, base_cx + asta_w / 2, base_cy],
            radius=int(asta_w * 0.5),
            fill=GRIGIO_OMBRA,
        )

    # --- Pomello rosso --------------------------------------------------
    palla_r = d * (0.165 if piccola else 0.155)
    palla_cy = asta_top
    dr.ellipse(
        [base_cx - palla_r, palla_cy - palla_r,
         base_cx + palla_r, palla_cy + palla_r],
        fill=ROSSO_PALLA,
    )
    # Riflesso in alto a sinistra: e' il dettaglio che fa leggere la
    # forma come una sfera invece che come un cerchio piatto.
    luce_r = palla_r * (0.42 if piccola else 0.34)
    dr.ellipse(
        [base_cx - palla_r * 0.45 - luce_r, palla_cy - palla_r * 0.45 - luce_r,
         base_cx - palla_r * 0.45 + luce_r, palla_cy - palla_r * 0.45 + luce_r],
        fill=ROSSO_LUCE,
    )

    # --- Pulsanti gialli -------------------------------------------------
    # A 16px due pulsanti diventerebbero due puntini indistinti: se ne
    # tiene uno solo, piu' grande e leggibile.
    btn_r = d * (0.085 if piccola else 0.070)
    if piccola:
        # Un solo pulsante, piu' grande: due cerchietti a 16px si
        # fonderebbero in una macchia gialla illeggibile.
        posizioni = [(d * 0.735, d * 0.60)]
    else:
        # Disposti in diagonale come su un vero pannello arcade, con uno
        # spazio netto fra loro perche' restino due forme distinte.
        posizioni = [(d * 0.695, d * 0.635), (d * 0.855, d * 0.545)]
    for cx, cy in posizioni:
        dr.ellipse([cx - btn_r, cy - btn_r, cx + btn_r, cy + btn_r], fill=GIALLO)
        # Riflesso, come sulla palla: coerente e aiuta a leggerli come
        # pulsanti tondi invece che come pallini piatti.
        if not piccola:
            lr = btn_r * 0.38
            dr.ellipse(
                [cx - btn_r * 0.35 - lr, cy - btn_r * 0.35 - lr,
                 cx - btn_r * 0.35 + lr, cy - btn_r * 0.35 + lr],
                fill=(255, 235, 150),
            )

    return img.resize((size, size), Image.LANCZOS)


def _voce_bmp(img: Image.Image) -> bytes:
    """Codifica un'immagine come DIB a 32 bit, il formato "classico" delle
    icone Windows.

    Perche' non usare PNG per tutto: Windows supporta le voci PNG dentro un
    .ico solo da Vista in poi. Le versioni precedenti mostrerebbero
    un'icona vuota. Le dimensioni piccole, che sono quelle davvero usate
    da Esplora risorse, vengono quindi salvate in BMP per sicurezza; per
    quelle grandi il PNG va benissimo e tiene il file molto piu' leggero.
    """
    w, h = img.size
    px = img.convert("RGBA").load()

    # BITMAPINFOHEADER: l'altezza e' doppia perche' comprende la maschera.
    header = struct.pack(
        "<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, w * h * 4, 0, 0, 0, 0
    )

    # I pixel vanno scritti dal basso verso l'alto, in ordine BGRA.
    corpo = bytearray()
    for y in range(h - 1, -1, -1):
        for x in range(w):
            r, g, b, a = px[x, y]
            corpo += bytes((b, g, r, a))

    # Maschera AND: inutile con il canale alfa, ma la struttura la
    # richiede comunque. Ogni riga va allineata a 4 byte.
    riga = ((w + 31) // 32) * 4
    maschera = bytes(riga * h)

    return header + bytes(corpo) + maschera


def _scrivi_ico(percorso: str, immagini) -> None:
    """Assembla il file .ico a mano, scegliendo per ogni dimensione il
    formato piu' compatibile (vedi _voce_bmp)."""
    voci = []
    for img in immagini:
        n = img.size[0]
        if n <= 48:
            voci.append((img, _voce_bmp(img)))
        else:
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            voci.append((img, buf.getvalue()))

    # Intestazione: riservato=0, tipo=1 (icona), numero di immagini
    out = bytearray(struct.pack("<HHH", 0, 1, len(voci)))
    offset = 6 + 16 * len(voci)
    for img, dati in voci:
        n = img.size[0]
        out += struct.pack(
            "<BBBBHHII",
            0 if n >= 256 else n,   # 0 significa 256
            0 if n >= 256 else n,
            0, 0, 1, 32,
            len(dati), offset,
        )
        offset += len(dati)
    for _, dati in voci:
        out += dati

    with open(percorso, "wb") as fh:
        fh.write(bytes(out))


def main():
    import os

    qui = os.path.dirname(os.path.abspath(__file__))
    progetto = os.path.dirname(qui)

    immagini = [disegna(n) for n in DIMENSIONI]

    ico = os.path.join(progetto, "MameCommander.ico")
    _scrivi_ico(ico, immagini)
    print(f"Creato: {ico}")

    png = os.path.join(progetto, "MameCommander.png")
    immagini[-1].save(png, format="PNG")
    print(f"Creato: {png}")


if __name__ == "__main__":
    main()
