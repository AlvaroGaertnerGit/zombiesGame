"""El jugador: controles FPS, stamina, vida, linterna y pistola."""
import math
import random

from panda3d.core import (AmbientLight, BitMask32, DirectionalLight, PerspectiveLens, PointLight, Spotlight,
                          TransparencyAttrib)
from ursina import Entity, Vec3, application, camera, held_keys, mouse, scene, time
from ursina.color import rgba

import sonidos
from world import altura

ALTURA_OJOS = 1.65
VEL_ANDAR = 4.2
VEL_CORRER = 7.2
GRAVEDAD = 16
FUERZA_SALTO = 5.5
SENSIBILIDAD = 40
RADIO = 0.4
VIDA_MAX = 100
CAPACIDAD_CARGADOR = 12
MUNICION_INICIAL = 48
TIEMPO_RECARGA = 1.4
CADENCIA = 0.16            # segundos mínimos entre disparos
POS_ARMA = Vec3(0.17, -0.165, 0.45)
COLOR_LINTERNA = (2.4, 2.2, 1.9, 1)


class Jugador(Entity):
    def __init__(self, juego):
        super().__init__()
        self.juego = juego
        # El pivote sube y baja la mirada; el jugador (raíz) solo gira a los lados
        self.pivote = Entity(parent=self, y=ALTURA_OJOS)
        camera.parent = self.pivote
        camera.position = (0, 0, 0)
        camera.rotation = (0, 0, 0)
        camera.fov = 85
        camera.clip_plane_near = 0.05
        camera.clip_plane_far = juego.mundo.distancia_vision   # más allá la niebla ya lo tapa todo
        self._crear_linterna()
        self._crear_pistola()
        self.reiniciar()

    # --- Creación ---

    def _crear_linterna(self):
        luz = Spotlight('linterna')
        lente = PerspectiveLens()
        # Sin shaders la luz se calcula solo en los vértices: un haz algo más ancho
        # hace que la linterna ilumine bien el suelo
        lente.set_fov(48 if self.juego.alta else 60)
        lente.set_near_far(0.3, 45)
        luz.set_lens(lente)
        luz.set_exponent(12)                     # borde del haz suave
        luz.set_attenuation((1, 0.05, 0.012))    # se apaga con la distancia
        if self.juego.alta:
            # Sombras: la linterna renderiza un mapa de profundidad propio.
            # La pistola se excluye para que no tape media pantalla con su sombra.
            luz.set_shadow_caster(True, 1024, 1024)
            luz.set_camera_mask(BitMask32.bit(1))
            application.base.cam.node().set_camera_mask(BitMask32.bit(0))
        self.luz_linterna = luz
        # En la mano derecha, algo separada de los ojos: así se ven las sombras
        self.nodo_linterna = camera.attach_new_node(luz)
        self.nodo_linterna.set_pos(0.25, -0.25, 0)
        scene.set_light(self.nodo_linterna)

        # Fogonazo: luz puntual que solo se enciende un instante al disparar
        self.luz_fogonazo = PointLight('fogonazo')
        self.luz_fogonazo.set_color((0, 0, 0, 1))
        self.luz_fogonazo.set_attenuation((1, 0.15, 0.08))
        self.nodo_fogonazo = camera.attach_new_node(self.luz_fogonazo)
        self.nodo_fogonazo.set_pos(0.25, -0.15, 0.9)
        scene.set_light(self.nodo_fogonazo)

    def _crear_pistola(self):
        self.arma = Entity(parent=camera, position=POS_ARMA, scale=0.7, rotation_y=-4,
                           add_to_scene_entities=False)
        metal, oscuro = rgba(0.32, 0.32, 0.34, 1), rgba(0.13, 0.13, 0.14, 1)

        def pieza(padre, escala, posicion, color):
            return Entity(parent=padre, model='cube', scale=escala, position=posicion, color=color,
                          add_to_scene_entities=False)

        pieza(self.arma, (0.065, 0.065, 0.3), (0, 0.035, 0), metal)              # corredera
        pieza(self.arma, (0.06, 0.045, 0.26), (0, -0.015, -0.01), oscuro)        # armazón
        pieza(self.arma, (0.03, 0.03, 0.02), (0, 0.04, 0.152), rgba(0, 0, 0, 1))  # boca del cañón
        pieza(self.arma, (0.01, 0.02, 0.012), (0, 0.075, 0.13), oscuro)         # mira delantera
        pieza(self.arma, (0.05, 0.018, 0.012), (0, 0.075, -0.13), oscuro)       # mira trasera
        pieza(self.arma, (0.05, 0.012, 0.09), (0, -0.075, 0.035), oscuro)       # guardamonte
        empunadura = Entity(parent=self.arma, position=(0, -0.09, -0.09), rotation_x=15,
                            add_to_scene_entities=False)
        pieza(empunadura, (0.058, 0.17, 0.085), (0, -0.05, 0), rgba(0.1, 0.08, 0.07, 1))

        # La pistola tiene su propia luz suave para que se vea siempre
        luz_arma = DirectionalLight('luz_arma')
        luz_arma.set_color((0.55, 0.53, 0.5, 1))
        nodo = camera.attach_new_node(luz_arma)
        nodo.set_hpr(30, -40, 0)
        ambiente_arma = AmbientLight('ambiente_arma')
        ambiente_arma.set_color((0.22, 0.22, 0.24, 1))
        nodo_ambiente = camera.attach_new_node(ambiente_arma)
        self.arma.set_light_off(1)
        self.arma.set_light(nodo, 2)
        self.arma.set_light(nodo_ambiente, 2)
        self.arma.set_light(self.nodo_fogonazo, 2)
        if self.juego.alta:
            self.arma.hide(BitMask32.bit(1))  # no proyecta sombra

        # Destello del disparo (una estrella de fuego delante del cañón)
        self.destello = Entity(parent=self.arma, model='quad', texture=self.juego.mundo.tex_destello,
                               position=(0, 0.04, 0.26), scale=0.22, enabled=False, add_to_scene_entities=False)
        self.destello.set_transparency(TransparencyAttrib.M_alpha)
        self.destello.set_light_off(3)
        self.destello.set_fog_off(3)
        self.destello.set_depth_write(False)
        self.destello.set_bin('fixed', 10)

    def reiniciar(self):
        self.position = Vec3(0, altura(0, 0), 0)
        self.rotation_y = 0
        self.pivote.rotation_x = 0
        self.pivote.rotation_z = 0
        self.vida = VIDA_MAX
        self.stamina = 100.0
        self.agotado = False
        self.vel_y = 0.0
        self.en_suelo = True
        self.cargador = CAPACIDAD_CARGADOR
        self.reserva = MUNICION_INICIAL
        self.recargando = 0.0
        self.espera_disparo = 0.0
        self.retroceso = 0.0
        self.tiempo_fogonazo = 0.0
        self.fase_paso = 0.0
        self.moviendo = False
        self.temblor = 0.0
        self.linterna_encendida = True
        self.luz_linterna.set_color(COLOR_LINTERNA)
        self.apagar_fogonazo()

    # --- Acciones ---

    def disparar(self):
        if self.recargando > 0 or self.espera_disparo > 0:
            return
        if self.cargador == 0:
            sonidos.reproducir('vacio', 0.8)
            self.espera_disparo = 0.25
            self.recargar()
            return
        self.cargador -= 1
        self.espera_disparo = CADENCIA
        self.retroceso = 1.0
        self.pivote.rotation_x -= 1.5   # la vista da un pequeño salto hacia arriba
        self.tiempo_fogonazo = 0.06
        self.destello.enabled = True
        self.destello.rotation_z = random.uniform(0, 360)
        self.destello.scale = random.uniform(0.18, 0.27)
        self.luz_fogonazo.set_color((3.0, 2.2, 1.1, 1))
        sonidos.reproducir('disparo', 0.9, random.uniform(0.93, 1.07))
        self.juego.disparo(camera.world_position, camera.forward)

    def apagar_fogonazo(self):
        self.tiempo_fogonazo = 0.0
        self.destello.enabled = False
        self.luz_fogonazo.set_color((0, 0, 0, 1))

    def recargar(self):
        if self.recargando > 0 or self.cargador == CAPACIDAD_CARGADOR or self.reserva == 0:
            return
        self.recargando = TIEMPO_RECARGA
        sonidos.reproducir('recarga', 0.8)

    def saltar(self):
        if self.en_suelo:
            self.vel_y = FUERZA_SALTO
            self.en_suelo = False

    def alternar_linterna(self):
        self.linterna_encendida = not self.linterna_encendida
        self.luz_linterna.set_color(COLOR_LINTERNA if self.linterna_encendida else (0, 0, 0, 1))
        sonidos.reproducir('linterna', 0.6)

    def recibir_dano(self, cantidad):
        if self.vida <= 0:
            return
        self.vida = max(0, self.vida - cantidad)
        self.temblor = 1.0
        sonidos.reproducir('herido', 0.9, random.uniform(0.9, 1.1))
        self.juego.ui.efecto_dano()
        if self.vida <= 0:
            self.juego.game_over()

    def curar(self, cantidad):
        self.vida = min(VIDA_MAX, self.vida + cantidad)

    # --- Cada fotograma ---

    def update(self):
        if self.juego.estado != 'jugando':
            return
        dt = time.dt
        self._mirar()
        self._moverse(dt)
        self._actualizar_arma(dt)

    def _mirar(self):
        if mouse.locked:
            self.rotation_y += mouse.velocity[0] * SENSIBILIDAD
            self.pivote.rotation_x -= mouse.velocity[1] * SENSIBILIDAD
        self.pivote.rotation_x = max(-85, min(85, self.pivote.rotation_x))

    def _moverse(self, dt):
        avance = held_keys['w'] - held_keys['s']
        lateral = held_keys['d'] - held_keys['a']
        direccion = self.forward * avance + self.right * lateral
        direccion.y = 0
        self.moviendo = direccion.length() > 0.01
        if self.moviendo:
            direccion = direccion.normalized()

        # Correr gasta stamina; al agotarse hay que esperar a recuperar un 30 %
        shift = held_keys['left shift'] or held_keys['right shift'] or held_keys['shift']
        corriendo = shift and self.moviendo and not self.agotado and self.stamina > 0
        if corriendo:
            self.stamina -= 25 * dt
            if self.stamina <= 0:
                self.stamina = 0
                self.agotado = True
        else:
            self.stamina = min(100.0, self.stamina + (12 if self.moviendo else 20) * dt)
            if self.agotado and self.stamina >= 30:
                self.agotado = False
        velocidad = VEL_CORRER if corriendo else VEL_ANDAR

        # Mover y salir de los troncos/rocas que toquemos (permite deslizarse)
        x = self.x + direccion.x * velocidad * dt
        z = self.z + direccion.z * velocidad * dt
        self.x, self.z = self.juego.mundo.empujar_fuera(x, z, RADIO)

        # Gravedad y salto sobre el terreno
        suelo = altura(self.x, self.z)
        if self.en_suelo:
            self.y = suelo
        else:
            self.vel_y -= GRAVEDAD * dt
            self.y += self.vel_y * dt
            if self.y <= suelo:
                self.y = suelo
                self.vel_y = 0
                self.en_suelo = True
                sonidos.reproducir('paso1', 0.9)

        # Balanceo de la cabeza y pasos
        if self.moviendo and self.en_suelo:
            antes = self.fase_paso
            self.fase_paso += dt * velocidad * 1.6
            if int(antes / math.pi) != int(self.fase_paso / math.pi):
                sonidos.reproducir(f'paso{random.randint(1, 3)}', 0.75 if corriendo else 0.5,
                                   random.uniform(0.9, 1.1))
            intensidad = velocidad / VEL_ANDAR
            self.pivote.y = ALTURA_OJOS + math.sin(self.fase_paso * 2) * 0.035 * intensidad
            self.pivote.x = math.sin(self.fase_paso) * 0.025 * intensidad
        else:
            self.pivote.y += (ALTURA_OJOS - self.pivote.y) * min(1, dt * 8)
            self.pivote.x += (0 - self.pivote.x) * min(1, dt * 8)

        # Temblor al recibir daño
        self.temblor = max(0.0, self.temblor - dt * 3)
        self.pivote.rotation_z = random.uniform(-3, 3) * self.temblor

    def _actualizar_arma(self, dt):
        self.espera_disparo = max(0.0, self.espera_disparo - dt)

        if self.recargando > 0:
            self.recargando -= dt
            if self.recargando <= 0:
                self.recargando = 0
                cantidad = min(CAPACIDAD_CARGADOR - self.cargador, self.reserva)
                self.cargador += cantidad
                self.reserva -= cantidad

        if self.tiempo_fogonazo > 0:
            self.tiempo_fogonazo -= dt
            if self.tiempo_fogonazo <= 0:
                self.apagar_fogonazo()

        # Retroceso (atrás y hacia arriba), bajada al recargar y vaivén al andar
        self.retroceso = max(0.0, self.retroceso - dt * 7)
        r = self.retroceso ** 1.5
        bajada = math.sin(math.pi * (1 - self.recargando / TIEMPO_RECARGA)) if self.recargando > 0 else 0
        vaiven = 1 if self.moviendo else 0
        self.arma.position = POS_ARMA + Vec3(math.sin(self.fase_paso) * 0.012 * vaiven,
                                             -abs(math.cos(self.fase_paso)) * 0.012 * vaiven - 0.14 * bajada,
                                             -0.07 * r)
        self.arma.rotation_x = -14 * r + 35 * bajada
        self.arma.rotation_z = -20 * bajada
