"""Zombis: figuras humanoides hechas con piezas que caminan balanceándose hacia el jugador."""
import math
import random

from ursina import Entity, Vec3, time
from ursina.color import rgba

import sonidos
from world import altura

RADIO = 0.35             # "grosor" del zombi para chocar con árboles y con otros zombis
DISTANCIA_ATAQUE = 1.25
DANO = 12
ESPERA_ATAQUE = 1.1      # segundos entre zarpazos
DISTANCIA_OIDO = 32      # a partir de aquí no se oyen sus gruñidos


def _pieza(padre, escala, posicion, color):
    """Un cubo que forma parte del cuerpo. No se registra como entidad suelta en
    Ursina (add_to_scene_entities=False) para que el juego vaya más rápido."""
    return Entity(parent=padre, model='cube', scale=escala, position=posicion, color=color,
                  add_to_scene_entities=False)


def rayo_esfera(origen, direccion, centro, radio):
    """Distancia a la que un rayo (dirección normalizada) toca una esfera, o None."""
    oc = origen - centro
    b = oc.dot(direccion)
    c = oc.dot(oc) - radio * radio
    disc = b * b - c
    if disc < 0:
        return None
    raiz = math.sqrt(disc)
    t = -b - raiz
    if t < 0:
        t = -b + raiz
    return t if t > 0 else None


class Zombi(Entity):
    def __init__(self, juego, posicion, velocidad):
        super().__init__(position=posicion)
        self.juego = juego
        self.velocidad = velocidad * random.uniform(0.85, 1.15)
        self.vida = 3
        self.muerto = False
        self.borrar = False          # el juego lo elimina cuando esto es True
        self.tiempo_muerto = 0.0
        self.fase = random.uniform(0, 6.28)
        self.espera_ataque = 0.0
        self.golpe = 0.0             # animación del zarpazo (1 -> 0)
        self.siguiente_grunido = random.uniform(1, 6)
        self.destello = 0.0          # parpadeo rojo al recibir un disparo
        self.empujon = Vec3(0, 0, 0)

        # Colores: piel verdosa y ropa sucia, distintos en cada zombi
        verde = random.uniform(0.75, 1.1)
        piel = rgba(0.32 * verde, 0.43 * verde, 0.25 * verde, 1)
        ropa = random.choice([rgba(0.25, 0.22, 0.18, 1), rgba(0.2, 0.24, 0.3, 1),
                              rgba(0.3, 0.12, 0.1, 1), rgba(0.28, 0.28, 0.26, 1)])
        pantalon = random.choice([rgba(0.12, 0.13, 0.18, 1), rgba(0.2, 0.17, 0.12, 1), rgba(0.1, 0.1, 0.1, 1)])

        # Cuerpo: gira desde la cadera, algo inclinado hacia delante
        self.cuerpo = Entity(parent=self, y=0.85, rotation_x=10, add_to_scene_entities=False)
        self.torso = _pieza(self.cuerpo, (0.5, 0.68, 0.27), (0, 0.32, 0), ropa)

        # Cada parte móvil tiene un pivote (cuello, hombro, cadera) que se anima, y
        # dentro un grupo con sus piezas. Al final cada grupo se funde en una sola
        # malla (se dibuja mucho más rápido). Se funde el grupo y no el pivote porque
        # fundir un nodo también "hornea" su propia rotación y la perdería.
        grupos = []

        def grupo(pivote):
            g = Entity(parent=pivote, add_to_scene_entities=False)
            grupos.append(g)
            return g

        # Cabeza ladeada, con boca oscura y ojos rojos que brillan en la oscuridad
        self.cabeza = Entity(parent=self.cuerpo, y=0.67, rotation_z=random.uniform(-18, 18),
                             add_to_scene_entities=False)
        g = grupo(self.cabeza)
        _pieza(g, (0.28, 0.32, 0.29), (0, 0.16, 0), piel)
        _pieza(g, (0.16, 0.05, 0.04), (0, 0.06, 0.14), rgba(0.06, 0.01, 0.01, 1))   # boca
        _pieza(g, (0.24, 0.05, 0.03), (0, 0.235, 0.14), piel)                      # ceja hundida
        for x in (-0.065, 0.065):
            ojo = _pieza(g, (0.035, 0.022, 0.02), (x, 0.2, 0.146), rgba(0.85, 0.12, 0.04, 1))
            ojo.set_light_off(1)

        # Brazos estirados hacia delante (el pivote está en el hombro)
        self.brazos = []
        for lado in (-1, 1):
            hombro = Entity(parent=self.cuerpo, position=(0.32 * lado, 0.58, 0), rotation_x=-80,
                            add_to_scene_entities=False)
            g = grupo(hombro)
            _pieza(g, (0.15, 0.36, 0.15), (0, -0.18, 0), ropa)   # manga
            _pieza(g, (0.12, 0.34, 0.12), (0, -0.52, 0), piel)   # antebrazo
            _pieza(g, (0.13, 0.12, 0.1), (0, -0.74, 0), piel)    # mano
            self.brazos.append(hombro)

        # Piernas (el pivote está en la cadera)
        self.piernas = []
        for lado in (-1, 1):
            cadera = Entity(parent=self, position=(0.13 * lado, 0.85, 0), add_to_scene_entities=False)
            g = grupo(cadera)
            _pieza(g, (0.19, 0.85, 0.2), (0, -0.42, 0), pantalon)
            _pieza(g, (0.2, 0.08, 0.3), (0, -0.82, 0.05), rgba(0.08, 0.07, 0.06, 1))
            self.piernas.append(cadera)

        for g in grupos:
            g.flatten_strong()

    # --- Disparos ---

    def impacto(self, origen, direccion):
        """Si el rayo del disparo le da, devuelve (distancia, 'cabeza' o 'cuerpo')."""
        zonas = [('cuerpo', self.torso.world_position, 0.36),
                 ('cuerpo', self.world_position + Vec3(0, 0.45, 0), 0.3)]
        if self.cabeza.enabled:
            zonas.append(('cabeza', self.cabeza.world_position + Vec3(0, 0.16, 0), 0.21))
        mejor = None
        for zona, centro, radio in zonas:
            t = rayo_esfera(origen, direccion, centro, radio)
            if t is not None and (mejor is None or t < mejor[0]):
                mejor = (t, zona)
        return mejor

    def recibir_disparo(self, zona, direccion):
        """Cabeza = muerte instantánea; cuerpo = 3 disparos. Devuelve True si muere."""
        self.vida = 0 if zona == 'cabeza' else self.vida - 1
        self.destello = 0.12
        self.empujon = Vec3(direccion.x, 0, direccion.z) * 2.5  # retrocede un poco
        sonidos.reproducir('impacto', 0.8, random.uniform(0.9, 1.1))
        if self.vida <= 0:
            self.morir(decapitado=zona == 'cabeza')
            return True
        return False

    def morir(self, decapitado):
        self.muerto = True
        self.tiempo_muerto = 0.0
        self.set_color_scale(1, 1, 1, 1)
        if decapitado:
            self.cabeza.enabled = False
        else:
            self._grunir(volumen=0.8, tono=0.6)  # último quejido, más grave

    # --- Cada fotograma ---

    def update(self):
        if self.juego.estado != 'jugando':
            return
        dt = time.dt
        if self.muerto:
            self._caer(dt)
            return

        jugador = self.juego.jugador
        dx, dz = jugador.x - self.x, jugador.z - self.z
        dist = max(0.01, math.hypot(dx, dz))
        self.rotation_y = math.degrees(math.atan2(dx, dz))  # mirar al jugador

        # Avanzar hacia el jugador
        mover = Vec3(0, 0, 0)
        if dist > 0.9:
            mover += Vec3(dx / dist, 0, dz / dist) * self.velocidad
        # Separarse de los otros zombis para no amontonarse
        for otro in self.juego.zombis:
            if otro is self or otro.muerto:
                continue
            ox, oz = self.x - otro.x, self.z - otro.z
            d = math.hypot(ox, oz)
            if 0 < d < 0.85:
                mover += Vec3(ox / d, 0, oz / d) * (0.85 - d) * 4
        mover += self.empujon
        self.empujon *= max(0.0, 1 - dt * 6)

        x, z = self.juego.mundo.empujar_fuera(self.x + mover.x * dt, self.z + mover.z * dt, RADIO)
        self.x, self.z = x, z
        self.y = altura(x, z)

        self._animar(dt)

        # Atacar si está pegado al jugador
        self.espera_ataque -= dt
        if dist < DISTANCIA_ATAQUE and self.espera_ataque <= 0:
            self.espera_ataque = ESPERA_ATAQUE
            self.golpe = 1.0
            jugador.recibir_dano(DANO)

        # Gruñir de vez en cuando
        self.siguiente_grunido -= dt
        if self.siguiente_grunido <= 0:
            self.siguiente_grunido = random.uniform(4, 9)
            self._grunir()

        # Parpadeo rojo al recibir un disparo
        if self.destello > 0:
            self.destello -= dt
            self.set_color_scale(2.2, 0.5, 0.5, 1) if self.destello > 0 else self.set_color_scale(1, 1, 1, 1)

    def _animar(self, dt):
        """Andar torpe: piernas alternas, cuerpo que se balancea y cabeza colgando."""
        self.fase += dt * (1.5 + self.velocidad * 2.0)
        s = math.sin(self.fase)
        self.piernas[0].rotation_x = 28 * s
        self.piernas[1].rotation_x = -28 * s
        self.cuerpo.rotation_z = 7 * s
        self.cuerpo.y = 0.85 + 0.04 * abs(s)
        self.cabeza.rotation_x = 12 + 10 * math.sin(self.fase * 0.5)
        self.golpe = max(0.0, self.golpe - dt * 4)
        for i, brazo in enumerate(self.brazos):
            brazo.rotation_x = -80 + 7 * math.sin(self.fase + i * 1.7) - 35 * self.golpe

    def _caer(self, dt):
        """Cae de espaldas, se queda en el suelo y luego se hunde en la tierra."""
        self.tiempo_muerto += dt
        avance = min(1.0, self.tiempo_muerto / 0.7)
        self.rotation_x = -85 * avance * avance
        if self.tiempo_muerto > 3:
            self.y -= dt * 0.5
        if self.tiempo_muerto > 5.5:
            self.borrar = True

    def _grunir(self, volumen=0.9, tono=None):
        jugador = self.juego.jugador
        dx, dz = self.x - jugador.x, self.z - jugador.z
        dist = max(0.1, math.hypot(dx, dz))
        if dist > DISTANCIA_OIDO:
            return
        # Más bajo cuanto más lejos, y por el altavoz del lado donde está el zombi
        derecha = jugador.right
        balance = max(-1.0, min(1.0, (dx * derecha.x + dz * derecha.z) / dist)) * 0.7
        sonidos.reproducir(f'grunido{random.randint(1, 3)}', volumen * (1 - dist / DISTANCIA_OIDO),
                           tono or random.uniform(0.8, 1.1), balance)
