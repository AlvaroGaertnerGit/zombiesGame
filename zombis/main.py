"""LA ÚLTIMA NOCHE - supervivencia contra zombis en primera persona con Ursina.

    python main.py          calidad automática (sombras y postprocesado si la gráfica lo permite)
    python main.py --bajo   fuerza los gráficos básicos (para PCs lentos)
"""
import json
import math
import random
import sys
from datetime import date
from pathlib import Path

from panda3d.core import NS_fatal, Notify, loadPrcFileData

# Permitir también OpenGL por software, para PCs sin driver de tarjeta gráfica
loadPrcFileData('', 'framebuffer-hardware false\n')

from ursina import Entity, Shader, Ursina, Vec3, application, camera, destroy, mouse, scene, time, window
from ursina.color import rgba

# Usamos las luces y la niebla de Panda3D en lugar de los shaders propios de Ursina
Entity.default_shader = None

import sonidos
from player import Jugador
from ui import Interfaz
from world import Mundo, Recogible, altura
from zombie import Zombi

ARCHIVO_RECORD = Path(__file__).parent / 'record.json'
MAX_ZOMBIS_VIVOS = 24
ALCANCE_DISPARO = 70

# Postprocesado (solo con GPU): desaturar, enfriar los colores, viñeta y grano de película
POSTPROCESADO_VERTICES = '''
#version 330
uniform mat4 p3d_ModelViewProjectionMatrix;
in vec4 p3d_Vertex;
in vec2 p3d_MultiTexCoord0;
out vec2 uv;
void main() {
    gl_Position = p3d_ModelViewProjectionMatrix * p3d_Vertex;
    uv = p3d_MultiTexCoord0;
}
'''
POSTPROCESADO_PIXELES = '''
#version 330
uniform sampler2D tex;
uniform float tiempo;
in vec2 uv;
out vec4 color;
void main() {
    vec3 c = texture(tex, uv).rgb;
    float lum = dot(c, vec3(0.299, 0.587, 0.114));
    c = mix(vec3(lum), c, 0.7);                 // colores apagados
    c *= vec3(0.92, 1.0, 1.1);                   // tono frío nocturno
    c = pow(max(c, 0.0), vec3(1.08));            // algo más de contraste en las sombras
    float d = length((uv - 0.5) * vec2(1.25, 1.0));
    c *= mix(1.0, 0.18, smoothstep(0.3, 0.85, d));  // viñeta
    float ruido = fract(sin(dot(uv * 1000.0 + tiempo * 61.0, vec2(12.9898, 78.233))) * 43758.5453);
    c += (ruido - 0.5) * 0.04;                   // grano
    color = vec4(c, 1.0);
}
'''


def detectar_calidad():
    """True si la gráfica permite shaders (GLSL 3.30 o más) y no se pidió --bajo."""
    if '--bajo' in sys.argv:
        return False
    gsg = application.base.win.gsg
    version = (gsg.driver_shader_version_major, gsg.driver_shader_version_minor)
    return bool(gsg.supports_glsl) and version >= (3, 30)


def cargar_record():
    try:
        return json.loads(ARCHIVO_RECORD.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'puntos': 0, 'oleada': 0, 'eliminados': 0}


class Juego(Entity):
    """Controla los estados (menu, jugando, pausa, fin), las oleadas y los disparos."""

    def __init__(self, alta):
        super().__init__()
        self.alta = alta
        self.estado = 'menu'
        self.reloj = 0.0
        self.zombis, self.recogibles, self.particulas = [], [], []
        self._reiniciar_estadisticas()
        self.record = cargar_record()

        self.mundo = Mundo(alta)
        self.jugador = Jugador(self)
        self.ui = Interfaz(self)
        self.viento = sonidos.reproducir_en_bucle('viento', 0.6)
        self.ir_al_menu()

    # --- Estados ---

    def _reiniciar_estadisticas(self):
        self.oleada = 0
        self.por_aparecer = 0
        self.velocidad_oleada = 1.3
        self.espera_aparicion = 0.0
        self.descanso = 2.0          # segundos hasta la primera oleada
        self.eliminados = 0
        self.cabezas = 0
        self.disparos = 0
        self.aciertos = 0
        self.puntos = 0
        self.tiempo_partida = 0.0
        self.espera_latido = 0.0

    def _limpiar(self):
        for lista in (self.zombis, self.recogibles, self.particulas):
            for entidad in lista:
                destroy(entidad)
            lista.clear()

    def ir_al_menu(self):
        self._limpiar()
        self._reiniciar_estadisticas()
        self.jugador.reiniciar()
        self.estado = 'menu'
        mouse.locked = False
        self.ui.mostrar('menu')

    def nueva_partida(self):
        self._limpiar()
        self._reiniciar_estadisticas()
        self.jugador.reiniciar()
        self.jugador.espera_disparo = 0.3   # que el clic en "JUGAR" no dispare
        self.estado = 'jugando'
        mouse.locked = True
        self.ui.mostrar('juego')

    def pausar(self):
        self.estado = 'pausa'
        mouse.locked = False
        self.jugador.apagar_fogonazo()
        self.ui.mostrar('pausa')

    def continuar(self):
        self.estado = 'jugando'
        mouse.locked = True
        self.ui.mostrar('juego')

    def game_over(self):
        self.estado = 'fin'
        mouse.locked = False
        self.jugador.apagar_fogonazo()
        estadisticas = {
            'oleada': self.oleada, 'eliminados': self.eliminados, 'cabezas': self.cabezas,
            'precision': round(100 * self.aciertos / self.disparos) if self.disparos else 0,
            'tiempo': self.tiempo_partida, 'puntos': self.puntos,
        }
        nuevo_record = self.puntos > self.record.get('puntos', 0)
        if nuevo_record:
            self.record = {'puntos': self.puntos, 'oleada': self.oleada,
                           'eliminados': self.eliminados, 'fecha': date.today().isoformat()}
            try:
                ARCHIVO_RECORD.write_text(json.dumps(self.record, indent=2), encoding='utf-8')
            except OSError as error:
                print('No se pudo guardar el récord:', error)
        self.ui.mostrar_fin(estadisticas, nuevo_record)

    def zombis_restantes(self):
        return self.por_aparecer + sum(1 for z in self.zombis if not z.muerto)

    # --- Entrada ---

    def input(self, tecla):
        if tecla == 'escape':
            if self.estado == 'jugando':
                self.pausar()
            elif self.estado == 'pausa':
                self.continuar()
            return
        if tecla == 'enter' and self.estado in ('menu', 'fin'):
            self.nueva_partida()
            return
        if self.estado != 'jugando':
            return
        if tecla == 'left mouse down':
            self.jugador.disparar()
        elif tecla == 'r':
            self.jugador.recargar()
        elif tecla == 'f':
            self.jugador.alternar_linterna()
        elif tecla == 'space':
            self.jugador.saltar()

    # --- Cada fotograma ---

    def update(self):
        dt = time.dt
        self.reloj += dt
        self.mundo.actualizar()
        if self.alta:
            camera.set_shader_input('tiempo', self.reloj)
        self.ui.actualizar(dt)

        if self.estado == 'menu':
            self.jugador.rotation_y += 5 * dt   # vista lenta del bosque detrás del menú
            return
        if self.estado != 'jugando':
            return

        self.tiempo_partida += dt
        self._oleadas(dt)
        self._actualizar_recogibles(dt)
        self._actualizar_particulas(dt)
        for zombi in [z for z in self.zombis if z.borrar]:
            self.zombis.remove(zombi)
            destroy(zombi)

        # Latido cuando queda poca vida
        if self.jugador.vida < 30:
            self.espera_latido -= dt
            if self.espera_latido <= 0:
                self.espera_latido = 0.9
                sonidos.reproducir('latido', 0.9)

    def _oleadas(self, dt):
        if self.descanso > 0:
            self.descanso -= dt
            if self.descanso <= 0:
                self._empezar_oleada()
            return
        vivos = sum(1 for z in self.zombis if not z.muerto)
        if self.por_aparecer > 0:
            # Los zombis van saliendo de la niebla poco a poco
            self.espera_aparicion -= dt
            if self.espera_aparicion <= 0 and vivos < MAX_ZOMBIS_VIVOS:
                posicion = self.mundo.posicion_aparicion(self.jugador.x, self.jugador.z)
                self.zombis.append(Zombi(self, posicion, self.velocidad_oleada))
                self.por_aparecer -= 1
                self.espera_aparicion = max(0.5, 2.2 - 0.15 * self.oleada)
        elif vivos == 0:
            premio = 250 * self.oleada
            self.puntos += premio
            self.ui.anunciar(f'OLEADA {self.oleada} SUPERADA', f'+{premio} puntos')
            self.descanso = 6.0

    def _empezar_oleada(self):
        self.oleada += 1
        self.por_aparecer = 4 + 3 * self.oleada                          # cada vez más zombis...
        self.velocidad_oleada = min(1.3 + 0.18 * (self.oleada - 1), 3.8)  # ...y más rápidos
        self.espera_aparicion = 0.5
        self.ui.anunciar(f'OLEADA {self.oleada}', 'Se acercan...')
        sonidos.reproducir('oleada', 0.9)

    # --- Disparos ---

    def disparo(self, origen, direccion):
        self.disparos += 1
        objetivo = None
        for zombi in self.zombis:
            if zombi.muerto:
                continue
            impacto = zombi.impacto(origen, direccion)
            if impacto and impacto[0] < ALCANCE_DISPARO and (objetivo is None or impacto[0] < objetivo[0]):
                objetivo = (*impacto, zombi)
        bloqueo = self.mundo.distancia_obstaculo(origen, direccion, ALCANCE_DISPARO)

        if objetivo and objetivo[0] < bloqueo:
            distancia, zona, zombi = objetivo
            self.aciertos += 1
            self._salpicar(origen + direccion * distancia, direccion, rgba(0.35, 0.02, 0.02, 1), 10)
            murio = zombi.recibir_disparo(zona, direccion)
            if murio:
                self._zombi_muerto(zombi, zona == 'cabeza')
            self.ui.marcador(murio, zona == 'cabeza')
        elif bloqueo < ALCANCE_DISPARO:
            # Astillas o esquirlas de piedra donde pega la bala
            self._salpicar(origen + direccion * bloqueo, -direccion, rgba(0.35, 0.28, 0.2, 1), 6)

    def _zombi_muerto(self, zombi, cabeza):
        self.eliminados += 1
        self.puntos += 150 if cabeza else 100
        if cabeza:
            self.cabezas += 1
            self.ui.avisar('¡A LA CABEZA!')
        suerte = random.random()
        tipo = 'municion' if suerte < 0.15 else 'botiquin' if suerte < 0.23 else None
        if tipo:
            self.recogibles.append(Recogible(tipo, Vec3(zombi.x, altura(zombi.x, zombi.z), zombi.z)))

    def _salpicar(self, punto, direccion, color, cantidad):
        for _ in range(cantidad):
            gota = Entity(model='cube', position=punto, scale=random.uniform(0.03, 0.07), color=color,
                          add_to_scene_entities=False)
            gota.velocidad = direccion * 1.5 + Vec3(random.uniform(-1.5, 1.5), random.uniform(0.5, 2.5),
                                                    random.uniform(-1.5, 1.5))
            gota.vida = random.uniform(0.4, 0.8)
            self.particulas.append(gota)

    def _actualizar_particulas(self, dt):
        for gota in list(self.particulas):
            gota.vida -= dt
            gota.velocidad.y -= 9.8 * dt
            gota.position += gota.velocidad * dt
            if gota.vida <= 0 or gota.y < altura(gota.x, gota.z):
                self.particulas.remove(gota)
                destroy(gota)

    def _actualizar_recogibles(self, dt):
        jugador = self.jugador
        for objeto in list(self.recogibles):
            sigue = objeto.actualizar(dt)
            cerca = math.hypot(objeto.x - jugador.x, objeto.z - jugador.z) < 1.4
            if cerca and objeto.tipo == 'municion':
                jugador.reserva += 24
                self.ui.avisar('+24 balas')
                sonidos.reproducir('recoger', 0.8)
                sigue = False
            elif cerca and objeto.tipo == 'botiquin' and jugador.vida < 100:
                jugador.curar(40)
                self.ui.avisar('+40 vida')
                sonidos.reproducir('recoger', 0.8)
                sigue = False
            if not sigue:
                self.recogibles.remove(objeto)
                destroy(objeto)


def crear_juego():
    sonidos.generar_sonidos()
    app = Ursina(title='La última noche', development_mode=False, fullscreen=False,
                 borderless=False, size=(1280, 720))
    window.fps_counter.enabled = False
    alta = detectar_calidad()
    if alta:
        scene.set_shader_auto()   # luz por píxel y sombras con el generador de shaders de Panda3D
        camera.shader = Shader(name='postprocesado', vertex=POSTPROCESADO_VERTICES,
                               fragment=POSTPROCESADO_PIXELES, default_input={'tiempo': 0.0})
    else:
        # Gráfica sin shaders (o --bajo): luz y niebla clásicas de OpenGL, sin texturas
        # en el mundo y ventana más pequeña, para que vaya fluido también por software
        application.base.render.set_shader_off(1000)
        camera.ui_render.set_shader_off(1000)
        window.size = (960, 540)
        # Los drivers OpenGL 1.1 avisan de funciones que no tienen; son avisos inofensivos
        Notify.ptr().get_category(':display:gsg:glgsg').set_severity(NS_fatal)
    print('Calidad gráfica:', 'ALTA (sombras + postprocesado)' if alta else 'BÁSICA (sin shaders)')
    juego = Juego(alta)
    return app, juego


if __name__ == '__main__':
    app, juego = crear_juego()
    app.run()
