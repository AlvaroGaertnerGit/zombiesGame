"""Interfaz: HUD (vida, stamina, balas, oleada, eliminados, punto de mira),
efectos de pantalla, menú de inicio, pausa y pantalla de Game Over."""
import math

from panda3d.core import TransparencyAttrib
from ursina import Button, Entity, Mesh, Text, application, camera, window
from ursina.color import rgba

from player import CAPACIDAD_CARGADOR, VIDA_MAX

ROJO_SANGRE = rgba(0.72, 0.07, 0.05, 1)
GRIS = rgba(0.7, 0.7, 0.7, 1)
CONTROLES = ('WASD moverse  ·  Ratón mirar  ·  Clic disparar  ·  R recargar\n'
             'Shift correr  ·  Espacio saltar  ·  F linterna  ·  Esc pausa')


def _texto(padre, texto, posicion, escala=1.0, color=None, origen=(0, 0)):
    return Text(parent=padre, text=texto, position=posicion, scale=escala, origin=origen,
                color=color or rgba(1, 1, 1, 1))


def _rectangulo(padre, posicion, escala, color, origen=(0, 0)):
    return Entity(parent=padre, model='quad', position=posicion, scale=escala, color=color, origin=origen)


def _vineta(padre, color, alfa_max, z):
    """Oscurece los bordes de la pantalla. Es un anillo de triángulos con
    transparencia por vértice: el centro no se dibuja (más rápido sin GPU)."""
    ancho = window.aspect_ratio
    anillos = ((0.42, 0.0), (0.62, alfa_max * 0.45), (0.85, alfa_max * 0.85), (1.6, alfa_max))
    segmentos = 32
    vertices, colores, triangulos = [], [], []
    for radio, alfa in anillos:
        for i in range(segmentos):
            ang = 2 * math.pi * i / segmentos
            vertices.append((math.cos(ang) * radio * ancho / 2, math.sin(ang) * radio / 2, 0))
            colores.append(rgba(color[0], color[1], color[2], alfa))
    for k in range(len(anillos) - 1):
        for i in range(segmentos):
            a, b = k * segmentos + i, k * segmentos + (i + 1) % segmentos
            c, d = a + segmentos, b + segmentos
            triangulos += [a, c, b, b, c, d]
    entidad = Entity(parent=padre, model=Mesh(vertices=vertices, triangles=triangulos, colors=colores), z=z)
    entidad.set_transparency(TransparencyAttrib.M_alpha)
    entidad.set_two_sided(True)
    return entidad


def _boton(padre, texto, y, accion):
    return Button(parent=padre, text=texto, y=y, scale=(0.34, 0.07), color=rgba(0.22, 0.04, 0.04, 0.92),
                  highlight_color=rgba(0.5, 0.08, 0.06, 1), pressed_color=rgba(0.12, 0.02, 0.02, 1),
                  on_click=accion)


def _poner(texto, valor, color=None):
    """Cambia un texto solo si es distinto: regenerar un Text es lento."""
    if texto.text != valor:
        texto.text = valor
    if color is not None and texto.color != color:
        texto.color = color


def formato_tiempo(segundos):
    return f'{int(segundos // 60)}:{int(segundos % 60):02d}'


class Interfaz:
    def __init__(self, juego):
        self.juego = juego
        ancho = window.aspect_ratio
        self.izq, self.der = -ancho / 2, ancho / 2

        # Efectos a pantalla completa (detrás del HUD)
        self.vineta = _vineta(camera.ui, (0, 0, 0), 0.85, z=5)
        self.vineta.enabled = not juego.alta   # con GPU la viñeta la hace el postprocesado
        self.rojo = _vineta(camera.ui, (0.6, 0, 0), 1.0, z=4)
        self.rojo.enabled = False
        self.alfa_dano = 0.0
        self.reloj = 0.0

        self._crear_hud()
        self._crear_menu()
        self._crear_pausa()
        self._crear_fin()

    # --- Construcción ---

    def _crear_hud(self):
        self.hud = Entity(parent=camera.ui)
        izq, der = self.izq, self.der

        # Punto de mira: cuatro rayitas y un punto
        blanco = rgba(1, 1, 1, 0.85)
        for x, y, sx, sy in ((0.016, 0, 0.012, 0.0025), (-0.016, 0, 0.012, 0.0025),
                             (0, 0.016, 0.0025, 0.012), (0, -0.016, 0.0025, 0.012), (0, 0, 0.003, 0.003)):
            _rectangulo(self.hud, (x, y), (sx, sy), blanco)
        # Marcador de impacto: una X que aparece un instante al acertar
        self.marca = Entity(parent=self.hud, enabled=False)
        for x, y, ang in ((1, 1, 45), (-1, 1, -45), (1, -1, -45), (-1, -1, 45)):
            _rectangulo(self.marca, (x * 0.02, y * 0.02), (0.016, 0.003), rgba(1, 1, 1, 1)).rotation_z = ang
        self.tiempo_marca = 0.0

        # Vida y stamina (abajo a la izquierda)
        _texto(self.hud, 'VIDA', (izq + 0.05, -0.355), 0.9, GRIS, (-0.5, 0))
        self.texto_vida = _texto(self.hud, '100', (izq + 0.37, -0.355), 0.9, rgba(1, 1, 1, 1), (0.5, 0))
        _rectangulo(self.hud, (izq + 0.05, -0.385), (0.32, 0.022), rgba(0, 0, 0, 0.6), (-0.5, 0))
        self.barra_vida = _rectangulo(self.hud, (izq + 0.05, -0.385, -0.01), (0.32, 0.022), ROJO_SANGRE, (-0.5, 0))
        _texto(self.hud, 'STAMINA', (izq + 0.05, -0.418), 0.75, GRIS, (-0.5, 0))
        _rectangulo(self.hud, (izq + 0.05, -0.443), (0.32, 0.011), rgba(0, 0, 0, 0.6), (-0.5, 0))
        self.barra_stamina = _rectangulo(self.hud, (izq + 0.05, -0.443, -0.01), (0.32, 0.011),
                                         rgba(0.85, 0.75, 0.3, 1), (-0.5, 0))

        # Balas (abajo a la derecha)
        self.texto_balas = _texto(self.hud, '12', (der - 0.16, -0.405), 3, rgba(1, 1, 1, 1), (0.5, 0))
        self.texto_reserva = _texto(self.hud, '/ 48', (der - 0.05, -0.415), 1.6, GRIS, (0.5, 0))
        self.texto_aviso = _texto(self.hud, '', (der - 0.05, -0.34), 1.0, rgba(1, 0.8, 0.3, 1), (0.5, 0))

        # Oleada (arriba en el centro) y estadísticas (arriba a la derecha)
        self.texto_oleada = _texto(self.hud, '', (0, 0.455), 1.6, ROJO_SANGRE)
        self.texto_restantes = _texto(self.hud, '', (0, 0.415), 0.9, GRIS)
        self.texto_eliminados = _texto(self.hud, '', (der - 0.05, 0.455), 1.1, rgba(1, 1, 1, 1), (0.5, 0))
        self.texto_puntos = _texto(self.hud, '', (der - 0.05, 0.42), 0.9, GRIS, (0.5, 0))
        self.texto_linterna = _texto(self.hud, '', (0, -0.44), 0.85, GRIS)

        # Avisos grandes en el centro (nueva oleada, recogidas...)
        self.banner = _texto(self.hud, '', (0, 0.17), 3.5, ROJO_SANGRE)
        self.subtitulo = _texto(self.hud, '', (0, 0.1), 1.3, GRIS)
        self.tiempo_banner = 0.0
        self.mensaje = _texto(self.hud, '', (0, -0.17), 1.2, rgba(0.8, 1, 0.7, 1))
        self.tiempo_mensaje = 0.0

    def _crear_menu(self):
        self.menu = Entity(parent=camera.ui, z=-1)
        _rectangulo(self.menu, (0, 0), (self.der * 2 + 0.1, 1.1), rgba(0, 0, 0, 0.55))
        _texto(self.menu, 'LA ÚLTIMA NOCHE', (0, 0.26), 5, ROJO_SANGRE)
        _texto(self.menu, 'Sobrevive a las hordas de zombis en el bosque', (0, 0.17), 1.3, GRIS)
        _boton(self.menu, 'JUGAR', 0.04, self.juego.nueva_partida)
        _boton(self.menu, 'SALIR', -0.05, application.quit)
        self.texto_record_menu = _texto(self.menu, '', (0, -0.16), 1.1, rgba(1, 0.85, 0.4, 1))
        _texto(self.menu, CONTROLES, (0, -0.32), 0.9, GRIS)
        _texto(self.menu, 'Pulsa ENTER o haz clic en JUGAR', (0, -0.42), 0.8, rgba(0.5, 0.5, 0.5, 1))

    def _crear_pausa(self):
        self.pausa = Entity(parent=camera.ui, z=-1)
        _rectangulo(self.pausa, (0, 0), (self.der * 2 + 0.1, 1.1), rgba(0, 0, 0, 0.6))
        _texto(self.pausa, 'PAUSA', (0, 0.2), 4, rgba(1, 1, 1, 1))
        _boton(self.pausa, 'CONTINUAR', 0.05, self.juego.continuar)
        _boton(self.pausa, 'REINICIAR', -0.04, self.juego.nueva_partida)
        _boton(self.pausa, 'MENÚ PRINCIPAL', -0.13, self.juego.ir_al_menu)
        _texto(self.pausa, CONTROLES, (0, -0.33), 0.9, GRIS)

    def _crear_fin(self):
        self.fin = Entity(parent=camera.ui, z=-1)
        _rectangulo(self.fin, (0, 0), (self.der * 2 + 0.1, 1.1), rgba(0.15, 0, 0, 0.7))
        _texto(self.fin, 'HAS MUERTO', (0, 0.33), 5, ROJO_SANGRE)
        self.texto_estadisticas = _texto(self.fin, '', (0, 0.12), 1.2, rgba(1, 1, 1, 1))
        self.texto_nuevo_record = _texto(self.fin, '', (0, -0.06), 1.6, rgba(1, 0.85, 0.3, 1))
        _boton(self.fin, 'REINTENTAR', -0.15, self.juego.nueva_partida)
        _boton(self.fin, 'MENÚ PRINCIPAL', -0.24, self.juego.ir_al_menu)
        _boton(self.fin, 'SALIR', -0.33, application.quit)

    # --- Cambiar de pantalla ---

    def mostrar(self, pantalla):
        """pantalla: 'menu', 'juego', 'pausa' o 'fin'."""
        self.menu.enabled = pantalla == 'menu'
        self.pausa.enabled = pantalla == 'pausa'
        self.fin.enabled = pantalla == 'fin'
        self.hud.enabled = pantalla == 'juego'
        if pantalla == 'menu':
            record = self.juego.record
            self.texto_record_menu.text = (f"Mejor puntuación: {record['puntos']}  (oleada {record['oleada']})"
                                           if record.get('puntos') else 'Aún no hay récord')
        if pantalla == 'juego':
            self.banner.text = self.subtitulo.text = self.mensaje.text = ''
            self.alfa_dano = 0.0

    def mostrar_fin(self, est, nuevo_record):
        self.texto_estadisticas.text = (
            f"Oleada alcanzada: {est['oleada']}\n"
            f"Zombis eliminados: {est['eliminados']}   (a la cabeza: {est['cabezas']})\n"
            f"Precisión: {est['precision']} %\n"
            f"Tiempo sobrevivido: {formato_tiempo(est['tiempo'])}\n"
            f"PUNTUACIÓN: {est['puntos']}      Mejor: {self.juego.record['puntos']}")
        self.texto_nuevo_record.text = '¡NUEVO RÉCORD!' if nuevo_record else ''
        self.mostrar('fin')

    # --- Efectos ---

    def efecto_dano(self):
        self.alfa_dano = 0.85

    def marcador(self, mortal, cabeza):
        self.marca.enabled = True
        self.marca.color = rgba(1, 0.15, 0.1, 1) if mortal else rgba(1, 1, 1, 1)
        self.marca.scale = 1.4 if cabeza else 1
        self.tiempo_marca = 0.15

    def anunciar(self, titulo, subtitulo='', duracion=3.0):
        self.banner.text, self.subtitulo.text = titulo, subtitulo
        self.tiempo_banner = duracion

    def avisar(self, texto):
        self.mensaje.text = texto
        self.tiempo_mensaje = 1.5

    # --- Cada fotograma ---

    def actualizar(self, dt):
        self.reloj += dt
        juego, jugador = self.juego, self.juego.jugador

        # Pantalla roja: destello al recibir daño + latido con poca vida
        self.alfa_dano = max(0.0, self.alfa_dano - dt * 1.5)
        alfa = self.alfa_dano
        if juego.estado in ('jugando', 'pausa') and jugador.vida < 30:
            alfa = max(alfa, 0.45 + 0.2 * math.sin(self.reloj * 6))
        if juego.estado == 'fin':
            alfa = 0.9
        # Si es transparente del todo no se dibuja (ahorra mucho sin tarjeta gráfica)
        self.rojo.enabled = alfa > 0.01
        if self.rojo.enabled:
            self.rojo.color = rgba(1, 1, 1, alfa)

        if not self.hud.enabled:
            return

        _poner(self.texto_vida, str(int(jugador.vida)))
        self.barra_vida.scale_x = 0.32 * jugador.vida / VIDA_MAX
        self.barra_stamina.scale_x = 0.32 * jugador.stamina / 100
        self.barra_stamina.color = rgba(0.6, 0.3, 0.2, 1) if jugador.agotado else rgba(0.85, 0.75, 0.3, 1)

        _poner(self.texto_balas, str(jugador.cargador),
               rgba(1, 0.3, 0.25, 1) if jugador.cargador <= 3 else rgba(1, 1, 1, 1))
        _poner(self.texto_reserva, f'/ {jugador.reserva}')
        if jugador.recargando > 0:
            aviso = 'RECARGANDO...'
        elif jugador.cargador == 0:
            aviso = 'SIN BALAS' if jugador.reserva == 0 else 'PULSA R'
        elif jugador.cargador <= 3 and jugador.reserva > 0 and jugador.cargador < CAPACIDAD_CARGADOR:
            aviso = 'R para recargar'
        else:
            aviso = ''
        _poner(self.texto_aviso, aviso)

        _poner(self.texto_oleada, f'OLEADA {juego.oleada}' if juego.oleada else '')
        _poner(self.texto_restantes, f'Zombis restantes: {juego.zombis_restantes()}' if juego.oleada else '')
        _poner(self.texto_eliminados, f'Eliminados: {juego.eliminados}')
        _poner(self.texto_puntos, f'Puntos: {juego.puntos}')
        _poner(self.texto_linterna, '' if jugador.linterna_encendida else 'Linterna apagada  [F]')

        if self.tiempo_marca > 0:
            self.tiempo_marca -= dt
            self.marca.enabled = self.tiempo_marca > 0
        if self.tiempo_banner > 0:
            self.tiempo_banner -= dt
            transparencia = round(min(1.0, self.tiempo_banner), 1)  # se desvanece el último segundo
            _poner(self.banner, self.banner.text, rgba(0.72, 0.07, 0.05, transparencia))
            _poner(self.subtitulo, self.subtitulo.text, rgba(0.7, 0.7, 0.7, transparencia))
            if self.tiempo_banner <= 0:
                _poner(self.banner, '')
                _poner(self.subtitulo, '')
        if self.tiempo_mensaje > 0:
            self.tiempo_mensaje -= dt
            if self.tiempo_mensaje <= 0:
                _poner(self.mensaje, '')
