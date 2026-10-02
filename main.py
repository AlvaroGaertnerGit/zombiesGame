# Laberinto en primera persona con pygame + OpenGL
# Solo usa funciones de OpenGL 1.1 para funcionar también sin tarjeta gráfica.
import json
import math
import os

import pygame
from OpenGL.GL import *
from OpenGL.GLU import *

from maze import NIVELES

# --- Ajustes ---
ANCHO, ALTO = 800, 600
ALTURA_OJOS = 0.5       # las paredes miden 1, así que los ojos van a media altura
VELOCIDAD = 2.5         # casillas por segundo
SENSIBILIDAD = 0.15     # grados que gira la vista por cada píxel de ratón
PITCH_MAX = 85          # límite para mirar arriba/abajo (en grados)
RADIO_JUGADOR = 0.2     # "grosor" del jugador para las colisiones
DISTANCIA_SALIDA = 0.6  # a esta distancia del cubo verde se gana el nivel

# Archivo donde se guardan los mejores tiempos (junto a este script)
ARCHIVO_RECORDS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "records.json")

# Colores (rojo, verde, azul) de 0 a 1
COLOR_PARED = (0.55, 0.42, 0.65)    # piedra morada
COLOR_SUELO_A = (0.40, 0.36, 0.30)  # baldosas en forma de tablero de ajedrez
COLOR_SUELO_B = (0.32, 0.29, 0.25)
COLOR_NIEBLA = (0.05, 0.05, 0.09, 1.0)


# ---------------------------------------------------------------------------
# Utilidades del mapa
# ---------------------------------------------------------------------------

def buscar(mapa, letra):
    """Devuelve el centro (x, z) de la casilla donde está 'letra'."""
    for z, fila in enumerate(mapa):
        x = fila.find(letra)
        if x != -1:
            return x + 0.5, z + 0.5
    raise ValueError(f"El nivel no tiene la casilla '{letra}'")


def es_pared(mapa, x, z):
    """True si el punto (x, z) cae dentro de una pared o fuera del mapa."""
    col, fila = math.floor(x), math.floor(z)
    if fila < 0 or fila >= len(mapa) or col < 0 or col >= len(mapa[0]):
        return True
    return mapa[fila][col] == "#"


def choca(mapa, x, z):
    """El jugador es un cuadrado de lado 2*RADIO. Choca si alguna esquina toca pared."""
    r = RADIO_JUGADOR
    return (es_pared(mapa, x - r, z - r) or es_pared(mapa, x + r, z - r) or
            es_pared(mapa, x - r, z + r) or es_pared(mapa, x + r, z + r))


def formato_tiempo(segundos):
    """Convierte 75.3 en '1:15.3'."""
    return f"{int(segundos // 60)}:{segundos % 60:04.1f}"


def cargar_records():
    try:
        with open(ARCHIVO_RECORDS, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}  # si no existe o está dañado, empezamos sin récords


def guardar_records(records):
    with open(ARCHIVO_RECORDS, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)


# ---------------------------------------------------------------------------
# Dibujo 3D
# ---------------------------------------------------------------------------

def configurar_opengl():
    """Ajustes que se hacen una sola vez: perspectiva, luz y niebla."""
    glMatrixMode(GL_PROJECTION)
    gluPerspective(70, ANCHO / ALTO, 0.05, 100.0)
    glMatrixMode(GL_MODELVIEW)

    glEnable(GL_DEPTH_TEST)
    glClearColor(*COLOR_NIEBLA)  # el fondo es del color de la niebla

    # Transparencias (para el texto y los paneles del menú)
    glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

    # Luz: el color de cada vértice (glColor) se usa como material
    glEnable(GL_LIGHTING)
    glEnable(GL_COLOR_MATERIAL)
    glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE)
    glLightModelfv(GL_LIGHT_MODEL_AMBIENT, (0.25, 0.25, 0.30, 1))  # luz mínima en todas partes

    # Luz 0: una "linterna" cálida que va con el jugador y se apaga con la distancia
    glEnable(GL_LIGHT0)
    glLightfv(GL_LIGHT0, GL_DIFFUSE, (1.0, 0.9, 0.7, 1))
    glLightf(GL_LIGHT0, GL_CONSTANT_ATTENUATION, 0.5)
    glLightf(GL_LIGHT0, GL_LINEAR_ATTENUATION, 0.3)
    glLightf(GL_LIGHT0, GL_QUADRATIC_ATTENUATION, 0.05)

    # Luz 1: brillo verde alrededor de la salida
    glEnable(GL_LIGHT1)
    glLightfv(GL_LIGHT1, GL_DIFFUSE, (0.2, 1.0, 0.3, 1))
    glLightf(GL_LIGHT1, GL_CONSTANT_ATTENUATION, 0.3)
    glLightf(GL_LIGHT1, GL_QUADRATIC_ATTENUATION, 0.8)

    # Niebla lineal: a partir de 2 casillas empieza, a 9 ya no se ve nada
    glEnable(GL_FOG)
    glFogi(GL_FOG_MODE, GL_LINEAR)
    glFogfv(GL_FOG_COLOR, COLOR_NIEBLA)
    glFogf(GL_FOG_START, 2.0)
    glFogf(GL_FOG_END, 9.0)


def dibujar_pared(mapa, x, z):
    """Dibuja las caras de la pared (x, z) que dan a un pasillo.
    Las caras pegadas a otra pared nunca se ven, así que se saltan."""
    x2, z2 = x + 1, z + 1
    # Un tono algo distinto por bloque para que parezca piedra
    tono = 0.8 + 0.2 * ((x * 7 + z * 13) % 5) / 4
    glColor3f(COLOR_PARED[0] * tono, COLOR_PARED[1] * tono, COLOR_PARED[2] * tono)

    if not es_pared(mapa, x + 0.5, z - 0.5):  # cara norte
        glNormal3f(0, 0, -1)
        glVertex3f(x, 0, z); glVertex3f(x, 1, z); glVertex3f(x2, 1, z); glVertex3f(x2, 0, z)
    if not es_pared(mapa, x + 0.5, z + 1.5):  # cara sur
        glNormal3f(0, 0, 1)
        glVertex3f(x, 0, z2); glVertex3f(x2, 0, z2); glVertex3f(x2, 1, z2); glVertex3f(x, 1, z2)
    if not es_pared(mapa, x - 0.5, z + 0.5):  # cara oeste
        glNormal3f(-1, 0, 0)
        glVertex3f(x, 0, z); glVertex3f(x, 0, z2); glVertex3f(x, 1, z2); glVertex3f(x, 1, z)
    if not es_pared(mapa, x + 1.5, z + 0.5):  # cara este
        glNormal3f(1, 0, 0)
        glVertex3f(x2, 0, z); glVertex3f(x2, 1, z); glVertex3f(x2, 1, z2); glVertex3f(x2, 0, z2)


def dibujar_baldosa(x, z):
    """Una casilla de suelo. Se dibuja una por casilla (y no un único rectángulo)
    porque la luz se calcula en los vértices: con más vértices queda mejor."""
    glColor3f(*(COLOR_SUELO_A if (x + z) % 2 == 0 else COLOR_SUELO_B))
    glNormal3f(0, 1, 0)
    glVertex3f(x, 0, z); glVertex3f(x, 0, z + 1); glVertex3f(x + 1, 0, z + 1); glVertex3f(x + 1, 0, z)


def crear_lista_nivel(mapa):
    """Guarda todo el dibujo del nivel en una 'display list' de OpenGL.
    Así se prepara una sola vez y luego se pinta entero con glCallList."""
    lista = glGenLists(1)
    glNewList(lista, GL_COMPILE)
    glBegin(GL_QUADS)
    for z, fila in enumerate(mapa):
        for x, casilla in enumerate(fila):
            if casilla == "#":
                dibujar_pared(mapa, x, z)
            else:
                dibujar_baldosa(x, z)
    glEnd()
    glEndList()
    return lista


def dibujar_cubo(m):
    """Cubo centrado en el origen con lado 2*m (cada cara en un verde distinto)."""
    caras = [
        ((0.2, 1.0, 0.3), [(-m, -m, m), (m, -m, m), (m, m, m), (-m, m, m)]),
        ((0.2, 1.0, 0.3), [(-m, -m, -m), (-m, m, -m), (m, m, -m), (m, -m, -m)]),
        ((0.1, 0.8, 0.2), [(-m, -m, -m), (-m, -m, m), (-m, m, m), (-m, m, -m)]),
        ((0.1, 0.8, 0.2), [(m, -m, -m), (m, m, -m), (m, m, m), (m, -m, m)]),
        ((0.6, 1.0, 0.6), [(-m, m, -m), (-m, m, m), (m, m, m), (m, m, -m)]),
        ((0.6, 1.0, 0.6), [(-m, -m, -m), (m, -m, -m), (m, -m, m), (-m, -m, m)]),
    ]
    glBegin(GL_QUADS)
    for color, vertices in caras:
        glColor3f(*color)
        for v in vertices:
            glVertex3f(*v)
    glEnd()


# ---------------------------------------------------------------------------
# Dibujo 2D (textos, paneles y minimapa)
# ---------------------------------------------------------------------------

def empezar_2d():
    """Cambia a una proyección plana en píxeles: (0, 0) es la esquina de arriba a la izquierda."""
    glDisable(GL_DEPTH_TEST)
    glDisable(GL_LIGHTING)
    glDisable(GL_FOG)
    glMatrixMode(GL_PROJECTION)
    glPushMatrix()
    glLoadIdentity()
    glOrtho(0, ANCHO, ALTO, 0, -1, 1)
    glMatrixMode(GL_MODELVIEW)
    glPushMatrix()
    glLoadIdentity()


def terminar_2d():
    """Vuelve a la proyección 3D."""
    glMatrixMode(GL_PROJECTION)
    glPopMatrix()
    glMatrixMode(GL_MODELVIEW)
    glPopMatrix()
    glEnable(GL_DEPTH_TEST)
    glEnable(GL_LIGHTING)
    glEnable(GL_FOG)


def rectangulo(x, y, ancho, alto, color):
    """Rectángulo relleno; color = (r, g, b, transparencia)."""
    glColor4f(*color)
    glBegin(GL_QUADS)
    glVertex2f(x, y); glVertex2f(x + ancho, y)
    glVertex2f(x + ancho, y + alto); glVertex2f(x, y + alto)
    glEnd()


def texto(fuente, cadena, x, y, color=(255, 255, 255), centrado=False):
    """Escribe texto: pygame lo convierte en una imagen y OpenGL copia sus píxeles."""
    superficie = fuente.render(cadena, True, color)
    ancho, alto = superficie.get_size()
    if centrado:
        x -= ancho // 2
    pixeles = pygame.image.tobytes(superficie, "RGBA", True)  # True = filas de abajo arriba
    # glDrawPixels pinta hacia arriba desde la esquina inferior izquierda
    glRasterPos2f(x, y + alto)
    glDrawPixels(ancho, alto, GL_RGBA, GL_UNSIGNED_BYTE, pixeles)


# ---------------------------------------------------------------------------
# El juego
# ---------------------------------------------------------------------------

class Juego:
    def __init__(self):
        self.fuente_titulo = pygame.font.Font(None, 80)
        self.fuente_grande = pygame.font.Font(None, 48)
        self.fuente = pygame.font.Font(None, 32)
        self.fuente_peq = pygame.font.Font(None, 24)

        self.records = cargar_records()
        self.listas = [crear_lista_nivel(mapa) for mapa in NIVELES]
        self.animacion = 0.0      # reloj para animar el cubo de salida
        self.tiempos = []         # tiempos de cada nivel en la partida actual
        self.nuevos_records = set()
        self.estado = "menu"      # menu, jugando, pausa, nivel_superado, victoria
        self.cargar_nivel(0)

    # --- Cambios de estado ---

    def cargar_nivel(self, numero):
        self.nivel = numero
        self.mapa = NIVELES[numero]
        self.x, self.z = buscar(self.mapa, "S")
        self.salida = buscar(self.mapa, "E")
        self.pitch = 0.0
        self.tiempo = 0.0
        # Mirar hacia el primer pasillo libre junto al inicio.
        # yaw 0 = hacia -Z, 90 = hacia +X, 180 = hacia +Z, 270 = hacia -X
        for yaw, (dx, dz) in ((0, (0, -1)), (90, (1, 0)), (180, (0, 1)), (270, (-1, 0))):
            if not es_pared(self.mapa, self.x + dx, self.z + dz):
                self.yaw = float(yaw)
                break

    def capturar_raton(self, activo):
        """Oculta el cursor y lo atrapa en la ventana (o lo suelta)."""
        pygame.mouse.set_visible(not activo)
        pygame.event.set_grab(activo)
        # El modo relativo hace que el ratón no se pare en el borde de la ventana
        pygame.mouse.set_relative_mode(activo)
        pygame.mouse.get_rel()  # descartar el movimiento acumulado

    def empezar_partida(self):
        self.tiempos = []
        self.nuevos_records = set()
        self.cargar_nivel(0)
        self.estado = "jugando"
        self.capturar_raton(True)

    def nivel_completado(self):
        self.tiempos.append(self.tiempo)
        clave = str(self.nivel + 1)
        if clave not in self.records or self.tiempo < self.records[clave]:
            self.records[clave] = round(self.tiempo, 2)
            self.nuevos_records.add(self.nivel)
            guardar_records(self.records)
        self.capturar_raton(False)
        if self.nivel == len(NIVELES) - 1:
            self.estado = "victoria"
        else:
            self.estado = "nivel_superado"

    def procesar_evento(self, evento):
        if evento.type != pygame.KEYDOWN:
            return
        tecla = evento.key
        enter = tecla in (pygame.K_RETURN, pygame.K_KP_ENTER)

        if self.estado == "menu" and enter:
            self.empezar_partida()
        elif self.estado == "jugando":
            if tecla == pygame.K_p:
                self.estado = "pausa"
                self.capturar_raton(False)
            elif tecla == pygame.K_r:
                self.cargar_nivel(self.nivel)
        elif self.estado == "pausa":
            if tecla == pygame.K_r:
                self.cargar_nivel(self.nivel)
            if tecla in (pygame.K_p, pygame.K_r):
                self.estado = "jugando"
                self.capturar_raton(True)
        elif self.estado == "nivel_superado" and enter:
            self.cargar_nivel(self.nivel + 1)
            self.estado = "jugando"
            self.capturar_raton(True)
        elif self.estado == "victoria" and enter:
            self.cargar_nivel(0)
            self.estado = "menu"

    # --- Lógica de cada fotograma ---

    def mover(self, mx, mz):
        """Mueve al jugador comprobando cada eje por separado.
        Si un eje choca se anula solo ese, y el otro sigue: así te deslizas por la pared."""
        if not choca(self.mapa, self.x + mx, self.z):
            self.x += mx
        if not choca(self.mapa, self.x, self.z + mz):
            self.z += mz

    def actualizar(self, dt):
        self.animacion += dt

        if self.estado == "menu":
            self.yaw = (self.yaw + 15 * dt) % 360  # la vista gira sola de fondo
            return
        if self.estado != "jugando":
            return

        self.tiempo += dt

        # --- Girar la vista con el ratón ---
        dx, dy = pygame.mouse.get_rel()
        self.yaw = (self.yaw + dx * SENSIBILIDAD) % 360
        self.pitch = max(-PITCH_MAX, min(PITCH_MAX, self.pitch + dy * SENSIBILIDAD))

        # --- Moverse con el teclado ---
        # Solo se usa el yaw: aunque mires arriba o abajo, caminas por el suelo
        rad = math.radians(self.yaw)
        delante_x, delante_z = math.sin(rad), -math.cos(rad)
        derecha_x, derecha_z = math.cos(rad), math.sin(rad)

        teclas = pygame.key.get_pressed()
        avance = teclas[pygame.K_w] - teclas[pygame.K_s]
        lateral = teclas[pygame.K_d] - teclas[pygame.K_a]
        mx = delante_x * avance + derecha_x * lateral
        mz = delante_z * avance + derecha_z * lateral
        largo = math.hypot(mx, mz)
        if largo > 0:
            # Normalizar para no ir más rápido en diagonal
            paso = VELOCIDAD * dt / largo
            self.mover(mx * paso, mz * paso)

        # --- ¿Hemos llegado a la salida? ---
        sx, sz = self.salida
        if math.hypot(self.x - sx, self.z - sz) < DISTANCIA_SALIDA:
            self.nivel_completado()

    # --- Dibujo ---

    def dibujar(self):
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        self.dibujar_mundo()

        empezar_2d()
        if self.estado in ("jugando", "pausa"):
            self.dibujar_hud()
            self.dibujar_minimapa()
        if self.estado == "menu":
            self.dibujar_menu()
        elif self.estado == "pausa":
            self.dibujar_pausa()
        elif self.estado == "nivel_superado":
            self.dibujar_nivel_superado()
        elif self.estado == "victoria":
            self.dibujar_victoria()
        terminar_2d()

    def dibujar_mundo(self):
        glLoadIdentity()
        # La linterna se coloca antes de mover la cámara: así va siempre con el jugador
        glLightfv(GL_LIGHT0, GL_POSITION, (0, 0, 0, 1))

        # Cámara: girar el mundo (arriba/abajo y luego izquierda/derecha) y desplazarlo
        glRotatef(self.pitch, 1, 0, 0)
        glRotatef(self.yaw, 0, 1, 0)
        glTranslatef(-self.x, -ALTURA_OJOS, -self.z)

        # La luz verde se coloca después: así queda fija en la salida
        sx, sz = self.salida
        glLightfv(GL_LIGHT1, GL_POSITION, (sx, 0.5, sz, 1))

        glCallList(self.listas[self.nivel])

        # Al superar el nivel estamos dentro del cubo: mejor no dibujarlo
        if self.estado in ("nivel_superado", "victoria"):
            return

        # Cubo de salida: brillante (sin luz), flotando y girando
        glDisable(GL_LIGHTING)
        glPushMatrix()
        glTranslatef(sx, 0.5 + 0.08 * math.sin(self.animacion * 3), sz)
        glRotatef(self.animacion * 90, 0, 1, 0)
        glRotatef(25, 1, 0, 1)
        dibujar_cubo(0.2)
        glPopMatrix()
        glEnable(GL_LIGHTING)

    def dibujar_hud(self):
        # Barra superior: nivel, cronómetro y récord
        rectangulo(0, 0, ANCHO, 40, (0, 0, 0, 0.55))
        texto(self.fuente, f"Nivel {self.nivel + 1}/{len(NIVELES)}", 15, 10)
        texto(self.fuente, formato_tiempo(self.tiempo), ANCHO // 2, 10, (255, 230, 120), centrado=True)
        record = self.records.get(str(self.nivel + 1))
        if record is not None:
            texto(self.fuente_peq, f"Récord: {formato_tiempo(record)}", ANCHO - 140, 13, (180, 180, 180))
        texto(self.fuente_peq, "P pausa   R reiniciar   Esc salir", 15, ALTO - 28, (170, 170, 170))

    def dibujar_minimapa(self):
        filas, columnas = len(self.mapa), len(self.mapa[0])
        celda = 160 / max(filas, columnas)  # el minimapa ocupa como mucho 160 px
        ox = ANCHO - columnas * celda - 12  # esquina de abajo a la derecha
        oy = ALTO - filas * celda - 12

        rectangulo(ox - 4, oy - 4, columnas * celda + 8, filas * celda + 8, (0, 0, 0, 0.6))
        for z, fila in enumerate(self.mapa):
            for x, casilla in enumerate(fila):
                if casilla == "#":
                    rectangulo(ox + x * celda, oy + z * celda, celda, celda, (0.55, 0.42, 0.65, 0.9))
                elif casilla == "E":
                    rectangulo(ox + x * celda, oy + z * celda, celda, celda, (0.2, 1.0, 0.3, 1))

        # Jugador: un punto rojo y una línea hacia donde mira
        px, pz = ox + self.x * celda, oy + self.z * celda
        rad = math.radians(self.yaw)
        tam = max(3, celda * 0.3)
        rectangulo(px - tam, pz - tam, tam * 2, tam * 2, (1, 0.2, 0.2, 1))
        glColor3f(1, 0.2, 0.2)
        glBegin(GL_LINES)
        glVertex2f(px, pz)
        glVertex2f(px + math.sin(rad) * celda * 1.5, pz - math.cos(rad) * celda * 1.5)
        glEnd()

    def panel(self):
        """Oscurece toda la pantalla para que se lea bien el texto encima."""
        rectangulo(0, 0, ANCHO, ALTO, (0, 0, 0, 0.6))

    def dibujar_menu(self):
        self.panel()
        texto(self.fuente_titulo, "LABERINTO", ANCHO // 2, 120, (120, 255, 140), centrado=True)
        texto(self.fuente, "Encuentra el cubo verde en cada nivel", ANCHO // 2, 210, centrado=True)
        texto(self.fuente_grande, "Pulsa ENTER para jugar", ANCHO // 2, 290, (255, 230, 120), centrado=True)
        controles = ["W/S: avanzar y retroceder    A/D: moverse de lado",
                     "Ratón: mirar    P: pausa    R: reiniciar nivel    Esc: salir"]
        for i, linea in enumerate(controles):
            texto(self.fuente_peq, linea, ANCHO // 2, 400 + i * 28, (190, 190, 190), centrado=True)

    def dibujar_pausa(self):
        self.panel()
        texto(self.fuente_titulo, "PAUSA", ANCHO // 2, 200, centrado=True)
        texto(self.fuente, "P para continuar    R para reiniciar el nivel", ANCHO // 2, 300,
              (200, 200, 200), centrado=True)

    def dibujar_nivel_superado(self):
        self.panel()
        texto(self.fuente_grande, f"¡Nivel {self.nivel + 1} superado!", ANCHO // 2, 170,
              (120, 255, 140), centrado=True)
        texto(self.fuente, f"Tiempo: {formato_tiempo(self.tiempos[-1])}", ANCHO // 2, 250, centrado=True)
        if self.nivel in self.nuevos_records:
            texto(self.fuente, "¡Nuevo récord!", ANCHO // 2, 290, (255, 230, 120), centrado=True)
        else:
            record = self.records[str(self.nivel + 1)]
            texto(self.fuente, f"Récord: {formato_tiempo(record)}", ANCHO // 2, 290,
                  (190, 190, 190), centrado=True)
        texto(self.fuente, "ENTER para el siguiente nivel", ANCHO // 2, 380, (255, 230, 120), centrado=True)

    def dibujar_victoria(self):
        self.panel()
        texto(self.fuente_titulo, "¡HAS ESCAPADO!", ANCHO // 2, 80, (120, 255, 140), centrado=True)
        # Tabla con tres columnas centradas en posiciones fijas
        columnas = (ANCHO // 2 - 180, ANCHO // 2, ANCHO // 2 + 180)
        for cx, titulo in zip(columnas, ("Nivel", "Tu tiempo", "Mejor tiempo")):
            texto(self.fuente, titulo, cx, 190, (190, 190, 190), centrado=True)
        for i, tiempo in enumerate(self.tiempos):
            color = (255, 230, 120) if i in self.nuevos_records else (255, 255, 255)
            valores = (str(i + 1), formato_tiempo(tiempo), formato_tiempo(self.records[str(i + 1)]))
            for cx, valor in zip(columnas, valores):
                texto(self.fuente, valor, cx, 235 + i * 40, color, centrado=True)
        if self.nuevos_records:
            texto(self.fuente_peq, "En amarillo: ¡nuevo récord!", ANCHO // 2, 365,
                  (255, 230, 120), centrado=True)
        texto(self.fuente, f"Total: {formato_tiempo(sum(self.tiempos))}", ANCHO // 2, 400, centrado=True)
        texto(self.fuente, "ENTER para volver al menú    Esc para salir", ANCHO // 2, 480,
              (200, 200, 200), centrado=True)


def main():
    pygame.init()
    pygame.display.set_mode((ANCHO, ALTO), pygame.DOUBLEBUF | pygame.OPENGL)
    pygame.display.set_caption("Laberinto")
    configurar_opengl()

    juego = Juego()
    reloj = pygame.time.Clock()
    ejecutando = True

    while ejecutando:
        # Segundos desde el último fotograma (limitado para que un tirón
        # no nos haga dar un salto enorme a través de una pared)
        dt = min(reloj.tick(60) / 1000.0, 0.05)

        for evento in pygame.event.get():
            if evento.type == pygame.QUIT:
                ejecutando = False
            elif evento.type == pygame.KEYDOWN and evento.key == pygame.K_ESCAPE:
                ejecutando = False
            else:
                juego.procesar_evento(evento)

        juego.actualizar(dt)
        juego.dibujar()
        pygame.display.flip()

    juego.capturar_raton(False)  # soltar el ratón antes de salir
    pygame.quit()


if __name__ == "__main__":
    main()
