"""Sonidos generados por código (sin descargar nada de internet).

La primera vez que se ejecuta el juego se crean archivos .wav en la carpeta
'sonidos'. Si ya existen, se reutilizan (así puedes sustituirlos por los tuyos).
"""
import math
import random
import struct
import wave
from pathlib import Path

from ursina import Audio

CARPETA = Path(__file__).parent / 'sonidos'
FRECUENCIA = 22050  # muestras por segundo


# ---------------------------------------------------------------------------
# Herramientas básicas de síntesis
# ---------------------------------------------------------------------------

def _vacio(segundos):
    return [0.0] * int(segundos * FRECUENCIA)


def _ruido(n, rnd):
    return [rnd.uniform(-1, 1) for _ in range(n)]


def _paso_bajo(muestras, a):
    """Filtro de un polo: cuanto más pequeño es 'a', más grave/apagado suena."""
    salida, y = [], 0.0
    for m in muestras:
        y += a * (m - y)
        salida.append(y)
    return salida


def _mezclar(destino, origen, inicio_seg, volumen=1.0):
    """Suma 'origen' dentro de 'destino' empezando en inicio_seg."""
    i0 = int(inicio_seg * FRECUENCIA)
    for i, m in enumerate(origen):
        if i0 + i < len(destino):
            destino[i0 + i] += m * volumen


def _clic(segundos, tono, caida, rnd):
    """Chasquido metálico corto: ruido + tono que se apagan muy rápido."""
    n = int(segundos * FRECUENCIA)
    r = _ruido(n, rnd)
    return [(r[i] * 0.6 + math.sin(2 * math.pi * tono * i / FRECUENCIA)) *
            math.exp(-i / FRECUENCIA * caida) for i in range(n)]


def _guardar(nombre, muestras):
    """Normaliza el volumen y guarda un .wav mono de 16 bits."""
    pico = max(1e-6, max(abs(m) for m in muestras))
    escala = 0.9 * 32767 / pico
    datos = struct.pack(f'<{len(muestras)}h', *(int(m * escala) for m in muestras))
    with wave.open(str(CARPETA / f'{nombre}.wav'), 'wb') as archivo:
        archivo.setnchannels(1)
        archivo.setsampwidth(2)
        archivo.setframerate(FRECUENCIA)
        archivo.writeframes(datos)


# ---------------------------------------------------------------------------
# Cada sonido del juego
# ---------------------------------------------------------------------------

def _disparo(rnd):
    n = int(0.6 * FRECUENCIA)
    crujido = _paso_bajo(_ruido(n, rnd), 0.6)
    cola = _paso_bajo(_ruido(n, rnd), 0.05)  # eco grave del bosque
    salida = []
    for i in range(n):
        t = i / FRECUENCIA
        golpe = math.sin(2 * math.pi * (95 - 50 * t) * t) * math.exp(-t * 14)
        salida.append(crujido[i] * math.exp(-t * 22) + golpe * 0.9 + cola[i] * 1.6 * math.exp(-t * 5))
    return salida


def _vacio_clic(rnd):
    return _clic(0.06, 2400, 220, rnd)


def _recarga(rnd):
    salida = _vacio(1.3)
    _mezclar(salida, _clic(0.08, 1300, 90, rnd), 0.10, 0.7)   # sacar cargador
    _mezclar(salida, _clic(0.10, 900, 70, rnd), 0.62, 1.0)    # meter cargador
    roce = _paso_bajo(_ruido(int(0.09 * FRECUENCIA), rnd), 0.3)
    _mezclar(salida, roce, 0.98, 0.5)                          # tirar de la corredera
    _mezclar(salida, _clic(0.08, 1700, 120, rnd), 1.08, 1.0)  # corredera vuelve
    return salida


def _paso(rnd):
    n = int(0.2 * FRECUENCIA)
    grave = _paso_bajo(_ruido(n, rnd), 0.06)
    hojas = _ruido(n, rnd)
    salida = []
    for i in range(n):
        t = i / FRECUENCIA
        ataque = min(1.0, t / 0.008)
        salida.append(ataque * (grave[i] * 3 * math.exp(-t * 22) + hojas[i] * 0.12 * math.exp(-t * 45)))
    return salida


def _grunido(rnd):
    duracion = rnd.uniform(1.2, 1.7)
    n = int(duracion * FRECUENCIA)
    f0 = rnd.uniform(75, 115)               # tono base de la voz
    gargara = rnd.uniform(7, 13)            # vibración "húmeda"
    fase_lenta = rnd.uniform(0, 6.28)
    aliento = _paso_bajo(_ruido(n, rnd), 0.12)
    salida, fase = [], 0.0
    for i in range(n):
        t = i / FRECUENCIA
        f = f0 * (1 + 0.22 * math.sin(2 * math.pi * 0.6 * t + fase_lenta) - 0.25 * t / duracion)
        f += 5 * math.sin(2 * math.pi * 5.5 * t)
        fase += 2 * math.pi * f / FRECUENCIA
        voz = sum(math.sin(k * fase) / k for k in range(1, 7))  # onda rica en armónicos
        modulacion = 0.55 + 0.45 * math.sin(2 * math.pi * gargara * t)
        env = min(1.0, t / 0.18) * min(1.0, (duracion - t) / 0.45)
        salida.append((voz * 0.7 + aliento[i] * 2.5) * modulacion * env)
    return _paso_bajo(salida, 0.18)


def _impacto(rnd):
    n = int(0.18 * FRECUENCIA)
    chof = _paso_bajo(_ruido(n, rnd), 0.25)
    return [chof[i] * math.exp(-i / FRECUENCIA * 30) +
            0.6 * math.sin(2 * math.pi * 140 * i / FRECUENCIA) * math.exp(-i / FRECUENCIA * 35)
            for i in range(n)]


def _herido(rnd):
    n = int(0.45 * FRECUENCIA)
    r = _paso_bajo(_ruido(n, rnd), 0.1)
    return [(math.sin(2 * math.pi * (70 - 30 * i / n) * i / FRECUENCIA) + r[i] * 1.5) *
            math.exp(-i / FRECUENCIA * 9) for i in range(n)]


def _recoger(rnd):
    salida = _vacio(0.45)
    for inicio, tono in ((0.0, 660), (0.11, 990)):
        nota = [math.sin(2 * math.pi * tono * i / FRECUENCIA) * math.exp(-i / FRECUENCIA * 9)
                for i in range(int(0.3 * FRECUENCIA))]
        _mezclar(salida, nota, inicio)
    return salida


def _linterna(rnd):
    return _clic(0.04, 3000, 300, rnd)


def _latido(rnd):
    salida = _vacio(0.7)
    for inicio, vol in ((0.0, 1.0), (0.22, 0.7)):
        golpe = [math.sin(2 * math.pi * 50 * i / FRECUENCIA) * math.exp(-i / FRECUENCIA * 16)
                 for i in range(int(0.25 * FRECUENCIA))]
        _mezclar(salida, golpe, inicio, vol)
    return salida


def _oleada(rnd):
    """Golpe grave tipo gong desafinado para anunciar cada oleada."""
    n = int(3.0 * FRECUENCIA)
    parciales = [(55, 1.0), (82.4, 0.6), (117, 0.45), (163, 0.3), (231, 0.2)]
    return [sum(a * math.sin(2 * math.pi * f * i / FRECUENCIA) for f, a in parciales) *
            math.exp(-i / FRECUENCIA * 1.3) * min(1.0, i / 200) for i in range(n)]


def _viento(rnd):
    """Viento en bucle: ruido filtrado con ráfagas lentas. Los extremos se funden
    para que el bucle no tenga cortes."""
    duracion, fundido = 8.0, 1.0
    n, m = int(duracion * FRECUENCIA), int(fundido * FRECUENCIA)
    grave = _paso_bajo(_ruido(n + m, rnd), 0.02)
    agudo = _paso_bajo(_ruido(n + m, rnd), 0.08)
    crudo = []
    for i in range(n + m):
        t = i / FRECUENCIA
        rafaga = 0.55 + 0.3 * math.sin(2 * math.pi * t / duracion) + 0.15 * math.sin(2 * math.pi * 3 * t / duracion)
        crudo.append((grave[i] * 4 + (agudo[i] - grave[i]) * 1.5 * rafaga) * rafaga)
    salida = crudo[:n]
    for i in range(m):
        mezcla = i / m
        salida[i] = crudo[i] * mezcla + crudo[n + i] * (1 - mezcla)
    return salida


SONIDOS = {
    'disparo': _disparo, 'vacio': _vacio_clic, 'recarga': _recarga,
    'paso1': _paso, 'paso2': _paso, 'paso3': _paso,
    'grunido1': _grunido, 'grunido2': _grunido, 'grunido3': _grunido,
    'impacto': _impacto, 'herido': _herido, 'recoger': _recoger,
    'linterna': _linterna, 'latido': _latido, 'oleada': _oleada, 'viento': _viento,
}


def generar_sonidos():
    """Crea los .wav que falten en la carpeta 'sonidos'."""
    CARPETA.mkdir(exist_ok=True)
    for semilla, (nombre, funcion) in enumerate(SONIDOS.items()):
        if not (CARPETA / f'{nombre}.wav').exists():
            _guardar(nombre, funcion(random.Random(semilla)))


def reproducir(nombre, volumen=1.0, tono=1.0, balance=0.0):
    """Reproduce un sonido una vez. Si el PC no tiene audio, simplemente no suena."""
    return Audio(CARPETA / f'{nombre}.wav', volume=volumen, pitch=tono,
                 balance=balance, auto_destroy=True)


def reproducir_en_bucle(nombre, volumen=1.0):
    return Audio(CARPETA / f'{nombre}.wav', volume=volumen, loop=True, autoplay=True)
