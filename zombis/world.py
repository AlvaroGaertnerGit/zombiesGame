"""El mundo: terreno con colinas, bosque, rocas, cielo nocturno con luna, luces,
niebla, colisiones con obstáculos y los objetos que se pueden recoger."""
import math
import random

from panda3d.core import AmbientLight, DirectionalLight, Fog, TransparencyAttrib
from PIL import Image, ImageDraw, ImageFilter, ImageOps
from ursina import Entity, Mesh, Texture, Vec3, camera, scene, window
from ursina.color import rgba

TAM_MAPA = 100           # el bosque va de -100 a 100 en X y en Z
LIMITE_JUGADOR = 85      # nadie puede salir de este cuadrado
TAM_CELDA = 8            # celdas para buscar obstáculos cercanos rápido
TAM_TROZO = 40           # el bosque se divide en trozos para dibujar solo lo visible
COLOR_NIEBLA = (0.030, 0.038, 0.050)


def altura(x, z):
    """Altura del terreno en (x, z): varias ondas suaves sumadas = colinas ligeras."""
    return (1.6 * math.sin(x * 0.045) * math.cos(z * 0.05)
            + 0.9 * math.sin(x * 0.11 + 1.3) * math.sin(z * 0.09 + 0.7)
            + 0.35 * math.sin(x * 0.27 + z * 0.21))


def normal_terreno(x, z):
    e = 0.5
    dx = (altura(x + e, z) - altura(x - e, z)) / (2 * e)
    dz = (altura(x, z + e) - altura(x, z - e)) / (2 * e)
    return Vec3(-dx, 1, -dz).normalized()


# ---------------------------------------------------------------------------
# Texturas generadas con PIL (nada se descarga)
#
# El color de cada objeto va en sus vértices; las texturas son "mapas de detalle"
# claros que solo lo matizan. Así, en PCs sin tarjeta gráfica se pueden quitar
# (son lo que más cuesta dibujar por software) y el mundo conserva sus colores.
# Todas miden potencias de 2: OpenGL 1.1 no admite otros tamaños.
# ---------------------------------------------------------------------------

def _textura(imagen):
    tex = Texture(imagen)
    tex.filtering = 'mipmap'
    tex._texture.set_anisotropic_degree(8)
    return tex


def textura_hierba(rnd):
    manchas = Image.effect_noise((256, 256), 70).filter(ImageFilter.GaussianBlur(3))
    fino = Image.effect_noise((256, 256), 90)
    img = ImageOps.colorize(Image.blend(manchas, fino, 0.45), black=(120, 135, 105), white=(255, 255, 235))
    dibujo = ImageDraw.Draw(img)
    for _ in range(2500):  # briznas de hierba
        x, y = rnd.randrange(256), rnd.randrange(256)
        tono = rnd.choice([(150, 175, 120), (210, 230, 170), (110, 120, 90), (255, 250, 200), (170, 140, 110)])
        dibujo.line((x, y, x + rnd.randint(-2, 2), y - rnd.randint(3, 9)), fill=tono)
    return _textura(img)


def textura_corteza(rnd):
    ruido = Image.effect_noise((64, 256), 80)
    vetas = ruido.resize((8, 256)).resize((64, 256)).filter(ImageFilter.GaussianBlur(1))  # rayas verticales
    return _textura(ImageOps.colorize(Image.blend(vetas, ruido, 0.3), black=(90, 80, 70), white=(255, 250, 240)))


def textura_follaje(rnd):
    return _textura(ImageOps.colorize(Image.effect_noise((128, 128), 100), black=(100, 120, 100), white=(255, 255, 240)))


def textura_roca(rnd):
    ruido = Image.effect_noise((128, 128), 60).filter(ImageFilter.GaussianBlur(1.2))
    img = ImageOps.colorize(Image.blend(ruido, Image.effect_noise((128, 128), 90), 0.3),
                            black=(110, 110, 105), white=(255, 255, 250))
    return _textura(img)


def textura_luna(rnd):
    tam = 256
    img = Image.new('RGBA', (tam, tam), (0, 0, 0, 0))
    centro, radio = tam / 2, tam * 0.2
    for y in range(tam):
        for x in range(tam):
            d = math.hypot(x - centro, y - centro)
            if d < radio:
                img.putpixel((x, y), (225, 228, 215, 255))
            else:  # halo que se desvanece
                a = max(0.0, 1 - (d - radio) / (tam / 2 - radio)) ** 2.5
                img.putpixel((x, y), (150, 165, 190, int(a * 120)))
    dibujo = ImageDraw.Draw(img)
    for _ in range(14):  # cráteres
        ang, dist = rnd.uniform(0, 6.28), rnd.uniform(0, radio * 0.75)
        cx, cy = centro + math.cos(ang) * dist, centro + math.sin(ang) * dist
        r = rnd.uniform(3, 11)
        dibujo.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(185, 188, 178, 255))
    return Texture(img)


def textura_destello():
    """Estrella de fuego para el fogonazo del disparo."""
    tam = 128
    img = Image.new('RGBA', (tam, tam), (0, 0, 0, 0))
    c = tam / 2
    for y in range(tam):
        for x in range(tam):
            dx, dy = (x - c) / c, (y - c) / c
            d = math.hypot(dx, dy)
            puntas = abs(math.cos(math.atan2(dy, dx) * 3)) ** 8  # 6 puntas
            a = max(0.0, 1 - d / (0.35 + 0.65 * puntas))
            if a > 0:
                img.putpixel((x, y), (255, int(200 + 55 * a), int(120 * a), int(255 * min(1, a * 1.6))))
    return Texture(img)


# ---------------------------------------------------------------------------
# Construcción de mallas
# ---------------------------------------------------------------------------

class Constructor:
    """Va acumulando triángulos y al final crea una única malla (mucho más
    rápido de dibujar que cientos de objetos sueltos)."""

    def __init__(self):
        self.vertices, self.normales, self.colores, self.uvs = [], [], [], []

    def triangulo(self, a, b, c, normal, color, uvs=((0, 0), (1, 0), (0, 1)), normales=None):
        """'color' puede ser un color para todo el triángulo o una tupla con uno por vértice."""
        colores = color if isinstance(color[0], tuple) else (color, color, color)
        # En Ursina la cara visible es la que tiene el producto vectorial hacia dentro:
        # si apunta hacia fuera, se invierte el orden de los vértices.
        if (b - a).cross(c - a).dot(normal) > 0:
            b, c = c, b
            uvs = (uvs[0], uvs[2], uvs[1])
            colores = (colores[0], colores[2], colores[1])
            if normales:
                normales = (normales[0], normales[2], normales[1])
        normales = normales or (normal, normal, normal)
        for v, n, uv, col in zip((a, b, c), normales, uvs, colores):
            self.vertices.append(v)
            self.normales.append(n)
            self.colores.append(col)
            self.uvs.append(uv)

    def cilindro(self, p0, p1, r0, r1, lados, color, rep_v=1.0):
        """Tronco o rama desde p0 hasta p1, con radio r0 abajo y r1 arriba."""
        eje = (p1 - p0).normalized()
        auxiliar = Vec3(1, 0, 0) if abs(eje.y) > 0.9 else Vec3(0, 1, 0)
        u = eje.cross(auxiliar).normalized()
        w = eje.cross(u).normalized()
        for i in range(lados):
            ang0, ang1 = 2 * math.pi * i / lados, 2 * math.pi * (i + 1) / lados
            d0 = u * math.cos(ang0) + w * math.sin(ang0)
            d1 = u * math.cos(ang1) + w * math.sin(ang1)
            a, b = p0 + d0 * r0, p0 + d1 * r0
            c, d = p1 + d0 * r1, p1 + d1 * r1
            u0, u1 = i / lados, (i + 1) / lados
            normal_cara = (d0 + d1).normalized()
            self.triangulo(a, b, c, normal_cara, color, ((u0, 0), (u1, 0), (u0, rep_v)), (d0, d1, d0))
            self.triangulo(b, d, c, normal_cara, color, ((u1, 0), (u1, rep_v), (u0, rep_v)), (d1, d1, d0))

    def cono(self, base, radio, alto, lados, color, rnd):
        """Capa de follaje de pino: cono con el borde algo irregular y caído."""
        punta = base + Vec3(0, alto, 0)
        borde = []
        for i in range(lados):
            ang = 2 * math.pi * i / lados + rnd.uniform(-0.15, 0.15)
            r = radio * rnd.uniform(0.8, 1.15)
            borde.append(base + Vec3(math.cos(ang) * r, rnd.uniform(-0.35, 0.05), math.sin(ang) * r))
        for i in range(lados):
            a, b = borde[i], borde[(i + 1) % lados]
            centro = (a + b) * 0.5
            normal = (Vec3(centro.x - base.x, 0, centro.z - base.z).normalized() + Vec3(0, radio / alto, 0)).normalized()
            self.triangulo(a, b, punta, normal, color, ((0, 0), (1, 0), (0.5, 1)))
            self.triangulo(a, b, base + Vec3(0, -0.1, 0), Vec3(0, -1, 0), color)  # cara de abajo

    def bulto(self, centro, radio, aplastado, color, rnd, lados=7, anillos=4):
        """Roca o arbusto: esfera de pocas caras con los vértices desplazados al azar."""
        puntos = {}
        for j in range(anillos + 1):
            fi = math.pi * j / anillos
            for i in range(lados):
                th = 2 * math.pi * i / lados
                r = radio * rnd.uniform(0.75, 1.2) if 0 < j < anillos else radio
                puntos[(i, j)] = centro + Vec3(math.sin(fi) * math.cos(th) * r,
                                               math.cos(fi) * r * aplastado,
                                               math.sin(fi) * math.sin(th) * r)
        for j in range(anillos):
            for i in range(lados):
                a, b = puntos[(i, j)], puntos[((i + 1) % lados, j)]
                c, d = puntos[(i, j + 1)], puntos[((i + 1) % lados, j + 1)]
                for tri in ((a, b, c), (b, d, c)):
                    medio = (tri[0] + tri[1] + tri[2]) / 3
                    normal = (medio - centro).normalized()
                    self.triangulo(*tri, normal, color, ((0, 0), (1, 0), (0, 1)))

    def crear_mesh(self):
        if not self.vertices:
            return None
        return Mesh(vertices=self.vertices, triangles=list(range(len(self.vertices))),
                    normals=self.normales, colors=self.colores, uvs=self.uvs)


# ---------------------------------------------------------------------------
# El mundo
# ---------------------------------------------------------------------------

class Mundo:
    def __init__(self, alta, semilla=7):
        self.alta = alta
        self.rnd = random.Random(semilla)
        self.obstaculos = {}   # celda -> lista de (x, z, radio, y_abajo, y_arriba)
        self.todos_obstaculos = []
        # Sin tarjeta gráfica todo se dibuja por software: menos detalle y menos distancia
        self.distancia_vision = 75 if alta else 55

        # Texturas de detalle solo con GPU (por software son lo más lento de dibujar)
        self.tex_hierba = textura_hierba(self.rnd) if alta else None
        self.tex_corteza = textura_corteza(self.rnd) if alta else None
        self.tex_follaje = textura_follaje(self.rnd) if alta else None
        self.tex_roca = textura_roca(self.rnd) if alta else None
        self.tex_destello = textura_destello()

        self._crear_terreno()
        self._crear_bosque()
        self._crear_cielo()
        self._crear_luces()
        self._crear_niebla()

    # --- Construcción ---

    def _crear_terreno(self):
        celdas = 110 if self.alta else 80   # cuadrícula de celdas x celdas
        paso = 2 * TAM_MAPA / celdas
        hierba, tierra_seca = (0.20, 0.27, 0.13), (0.24, 0.19, 0.12)
        vertices, normales, colores, uvs, triangulos = [], [], [], [], []
        for j in range(celdas + 1):
            for i in range(celdas + 1):
                x, z = -TAM_MAPA + i * paso, -TAM_MAPA + j * paso
                vertices.append(Vec3(x, altura(x, z), z))
                normales.append(normal_terreno(x, z))
                uvs.append((x / 3, z / 3))  # la textura se repite cada 3 metros
                # Manchas de tierra y hojas secas para que no se vea todo igual
                tierra = math.sin(x * 0.13 + 2) * math.sin(z * 0.17) + 0.4 * math.sin(x * 0.4 + z * 0.3)
                tierra = min(1.0, max(0.0, tierra))
                tono = self.rnd.uniform(0.8, 1.05)
                colores.append(tuple(tono * (h * (1 - tierra) + t * tierra) for h, t in zip(hierba, tierra_seca)) + (1,))
        ancho = celdas + 1
        for j in range(celdas):
            for i in range(celdas):
                v00 = j * ancho + i
                v10, v01, v11 = v00 + 1, v00 + ancho, v00 + ancho + 1
                triangulos += [v00, v10, v01, v10, v11, v01]
        malla = Mesh(vertices=vertices, triangles=triangulos, normals=normales, colors=colores, uvs=uvs)
        self.terreno = Entity(model=malla, texture=self.tex_hierba)

    def _sitio_libre(self, radio_seguro=7):
        """Posición al azar del bosque, lejos del centro (donde empieza el jugador)."""
        while True:
            x = self.rnd.uniform(-TAM_MAPA + 2, TAM_MAPA - 2)
            z = self.rnd.uniform(-TAM_MAPA + 2, TAM_MAPA - 2)
            if math.hypot(x, z) > radio_seguro:
                return x, z

    def _crear_bosque(self):
        trozos = {}

        def constructor(x, z, material):
            clave = (math.floor(x / TAM_TROZO), math.floor(z / TAM_TROZO), material)
            if clave not in trozos:
                trozos[clave] = Constructor()
            return trozos[clave]

        alta = self.alta
        num_arboles, capas, lados = (520, 4, 9) if alta else (300, 3, 7)
        for _ in range(num_arboles):
            x, z = self._sitio_libre()
            y = altura(x, z) - 0.3
            corteza = constructor(x, z, 'corteza')
            tono = self.rnd.uniform(0.7, 1.0)
            if self.rnd.random() < 0.72:
                # Pino: tronco + capas de follaje en forma de cono
                alto = self.rnd.uniform(8, 14)
                radio = self.rnd.uniform(0.22, 0.38)
                corteza.cilindro(Vec3(x, y, z), Vec3(x, y + alto, z), radio, radio * 0.3, 7 if alta else 5,
                                 (0.30 * tono, 0.23 * tono, 0.17 * tono, 1), rep_v=alto / 3)
                follaje = constructor(x, z, 'follaje')
                ancho = self.rnd.uniform(2.2, 3.4)
                verde = (0.08 * tono, 0.17 * tono, 0.09 * tono, 1)
                for k in range(capas):
                    f = k / capas
                    base = Vec3(x, y + alto * (0.3 + 0.62 * f), z)
                    follaje.cono(base, ancho * (1 - f * 0.7), alto * (0.28 if alta else 0.34), lados, verde, self.rnd)
                self._anadir_obstaculo(x, z, radio + 0.15, y, y + alto)
            else:
                # Árbol muerto: tronco retorcido con ramas desnudas
                alto = self.rnd.uniform(6, 10)
                radio = self.rnd.uniform(0.2, 0.32)
                gris = (0.30 * tono, 0.27 * tono, 0.24 * tono, 1)
                cima = Vec3(x + self.rnd.uniform(-0.8, 0.8), y + alto, z + self.rnd.uniform(-0.8, 0.8))
                corteza.cilindro(Vec3(x, y, z), cima, radio, radio * 0.25, 6, gris, rep_v=alto / 3)
                for _ in range(self.rnd.randint(3, 6)):
                    t = self.rnd.uniform(0.35, 0.85)
                    inicio = Vec3(x, y, z) + (cima - Vec3(x, y, z)) * t
                    ang = self.rnd.uniform(0, 6.28)
                    largo = self.rnd.uniform(1.2, 3.0) * (1.1 - t)
                    fin = inicio + Vec3(math.cos(ang) * largo, self.rnd.uniform(0.4, 1.5), math.sin(ang) * largo)
                    corteza.cilindro(inicio, fin, radio * 0.35 * (1 - t * 0.5), 0.02, 4, gris)
                self._anadir_obstaculo(x, z, radio + 0.15, y, y + alto)

        for _ in range(170 if alta else 120):  # rocas
            x, z = self._sitio_libre(5)
            r = self.rnd.uniform(0.4, 1.6)
            y = altura(x, z)
            tono = self.rnd.uniform(0.3, 0.45)
            constructor(x, z, 'roca').bulto(Vec3(x, y - r * 0.15, z), r, 0.65, (tono, tono, tono * 0.95, 1), self.rnd)
            self._anadir_obstaculo(x, z, r * 0.85, y - 1, y + r * 0.55)

        for _ in range(260 if alta else 110):  # arbustos (no bloquean el paso)
            x, z = self._sitio_libre(4)
            r = self.rnd.uniform(0.4, 0.9)
            tono = self.rnd.uniform(0.6, 1.0)
            constructor(x, z, 'follaje').bulto(Vec3(x, altura(x, z), z), r, 0.7,
                                               (0.12 * tono, 0.2 * tono, 0.08 * tono, 1), self.rnd, lados=6, anillos=3)

        texturas = {'corteza': self.tex_corteza, 'follaje': self.tex_follaje, 'roca': self.tex_roca}
        self.trozos = []
        for (_, _, material), cons in trozos.items():
            self.trozos.append(Entity(model=cons.crear_mesh(), texture=texturas[material]))

    def _crear_cielo(self):
        """Cúpula con degradado (color por vértice, sin textura), estrellas y luna.
        Sigue a la cámara, así que siempre parece estar "en el infinito"."""
        cupula = Constructor()
        niebla, cenit = COLOR_NIEBLA, (0.008, 0.012, 0.03)

        def color_altura(y):
            mezcla = min(1.0, max(0.0, (y - 0.02) / 0.5)) ** 0.7  # niebla en el horizonte
            return tuple(n * (1 - mezcla) + c * mezcla for n, c in zip(niebla, cenit)) + (1,)

        def punto(lat, lon):
            return Vec3(math.cos(lat) * math.cos(lon), math.sin(lat), math.cos(lat) * math.sin(lon))

        latitudes = [math.radians(a) for a in (-30, 0, 6, 15, 30, 50, 70, 90)]
        segmentos = 24
        for j in range(len(latitudes) - 1):
            for i in range(segmentos):
                lon0, lon1 = 2 * math.pi * i / segmentos, 2 * math.pi * (i + 1) / segmentos
                a, b = punto(latitudes[j], lon0), punto(latitudes[j], lon1)
                c, d = punto(latitudes[j + 1], lon0), punto(latitudes[j + 1], lon1)
                for tri in ((a, b, c), (b, d, c)):
                    hacia_dentro = -(tri[0] + tri[1] + tri[2]).normalized()  # se ve desde dentro
                    cupula.triangulo(*tri, hacia_dentro, tuple(color_altura(v.y) for v in tri))
        radio = self.distancia_vision * 0.9   # tiene que caber dentro del plano lejano de la cámara
        self.cielo = Entity(model=cupula.crear_mesh(), scale=radio)

        # Estrellas: puntos de distintos brillos, más visibles cuanto más arriba
        estrellas, colores = [], []
        for _ in range(450):
            lat = math.asin(self.rnd.uniform(0.2, 1.0))
            v = punto(lat, self.rnd.uniform(0, 2 * math.pi)) * 0.97
            brillo = self.rnd.uniform(0.25, 0.9) * min(1.0, (v.y - 0.15) * 2.5)
            estrellas.append(v)
            colores.append((brillo, brillo, min(1.0, brillo * 1.15), 1))
        Entity(parent=self.cielo, model=Mesh(vertices=estrellas, colors=colores, mode='point',
                                             thickness=2, render_points_in_3d=False))

        self.cielo.set_light_off(1)
        self.cielo.set_fog_off(1)
        self.cielo.set_bin('background', 0)
        self.cielo.set_depth_write(False)

        self.direccion_luna = Vec3(-0.45, 0.42, 0.78).normalized()
        self.luna = Entity(parent=self.cielo, model='quad', texture=textura_luna(self.rnd),
                           position=self.direccion_luna * 0.85, scale=0.22)
        self.luna.set_billboard_point_eye()
        self.luna.set_transparency(TransparencyAttrib.M_alpha)
        self.luna.set_light_off(1)
        self.luna.set_fog_off(1)
        self.luna.set_bin('background', 1)
        self.luna.set_depth_write(False)

    def _crear_luces(self):
        ambiente = AmbientLight('ambiente')
        ambiente.set_color((0.035, 0.04, 0.06, 1))  # casi a oscuras
        scene.set_light(scene.attach_new_node(ambiente))

        luz_luna = DirectionalLight('luna')
        luz_luna.set_color((0.09, 0.11, 0.18, 1))   # luz fría y débil
        nodo = scene.attach_new_node(luz_luna)
        nodo.set_pos(self.direccion_luna * 100)
        nodo.look_at(0, 0, 0)
        scene.set_light(nodo)

    def _crear_niebla(self):
        niebla = Fog('niebla')
        niebla.set_color(*COLOR_NIEBLA)
        niebla.set_exp_density(0.055)   # niebla exponencial: densa a partir de ~20 m
        scene.set_fog(niebla)
        self.niebla = niebla
        window.color = rgba(*COLOR_NIEBLA, 1)

    # --- Cada fotograma ---

    def actualizar(self):
        self.cielo.position = camera.world_position

    # --- Colisiones ---

    def _anadir_obstaculo(self, x, z, radio, y_abajo, y_arriba):
        obstaculo = (x, z, radio, y_abajo, y_arriba)
        self.todos_obstaculos.append(obstaculo)
        clave = (math.floor(x / TAM_CELDA), math.floor(z / TAM_CELDA))
        self.obstaculos.setdefault(clave, []).append(obstaculo)

    def empujar_fuera(self, x, z, radio):
        """Si el círculo (x, z, radio) se mete en un tronco o roca, lo saca por el
        lado más cercano. Así se puede deslizar alrededor de los obstáculos."""
        cx, cz = math.floor(x / TAM_CELDA), math.floor(z / TAM_CELDA)
        for i in (cx - 1, cx, cx + 1):
            for j in (cz - 1, cz, cz + 1):
                for ox, oz, r, _, _ in self.obstaculos.get((i, j), ()):
                    dx, dz = x - ox, z - oz
                    d = math.hypot(dx, dz)
                    minimo = r + radio
                    if d < minimo:
                        if d < 1e-4:
                            dx, dz, d = 1.0, 0.0, 1.0
                        x, z = ox + dx / d * minimo, oz + dz / d * minimo
        limite = LIMITE_JUGADOR
        return max(-limite, min(limite, x)), max(-limite, min(limite, z))

    def distancia_obstaculo(self, origen, direccion, maximo):
        """Distancia a la que un disparo choca con un tronco o una roca (o 'maximo')."""
        mejor = maximo
        dx, dz = direccion.x, direccion.z
        largo2 = dx * dx + dz * dz
        if largo2 < 1e-8:
            return mejor
        for ox, oz, r, y0, y1 in self.todos_obstaculos:
            # Círculo en 2D y luego se comprueba la altura del impacto
            fx, fz = origen.x - ox, origen.z - oz
            b = fx * dx + fz * dz
            c = fx * fx + fz * fz - r * r
            disc = b * b - largo2 * c
            if disc < 0:
                continue
            t = (-b - math.sqrt(disc)) / largo2
            if 0 < t < mejor and y0 <= origen.y + direccion.y * t <= y1:
                mejor = t
        return mejor

    def posicion_aparicion(self, x_jugador, z_jugador):
        """Punto oculto en la niebla, a 40-50 m del jugador, para que salga un zombi."""
        for _ in range(50):
            ang = self.rnd.uniform(0, 2 * math.pi)
            dist = self.rnd.uniform(40, 50)
            x, z = x_jugador + math.cos(ang) * dist, z_jugador + math.sin(ang) * dist
            if abs(x) < LIMITE_JUGADOR and abs(z) < LIMITE_JUGADOR:
                x, z = self.empujar_fuera(x, z, 0.4)
                return Vec3(x, altura(x, z), z)
        # Si el jugador está en una esquina, aparece en el lado contrario
        x, z = -math.copysign(LIMITE_JUGADOR - 2, x_jugador), -math.copysign(LIMITE_JUGADOR - 2, z_jugador)
        return Vec3(x, altura(x, z), z)


# ---------------------------------------------------------------------------
# Objetos que sueltan los zombis
# ---------------------------------------------------------------------------

class Recogible(Entity):
    """Caja de munición o botiquín que flota y gira hasta que lo recoges."""
    DURACION = 30

    def __init__(self, tipo, posicion):
        super().__init__(position=posicion)
        self.tipo = tipo
        self.tiempo = 0.0
        self.modelo = Entity(parent=self, y=0.45, add_to_scene_entities=False)
        if tipo == 'municion':
            Entity(parent=self.modelo, model='cube', scale=(0.5, 0.3, 0.32), color=rgba(0.25, 0.32, 0.15, 1),
                   add_to_scene_entities=False)
            Entity(parent=self.modelo, model='cube', scale=(0.51, 0.08, 0.33), color=rgba(0.95, 0.75, 0.15, 1),
                   add_to_scene_entities=False)
        else:
            Entity(parent=self.modelo, model='cube', scale=(0.45, 0.32, 0.3), color=rgba(0.92, 0.92, 0.9, 1),
                   add_to_scene_entities=False)
            for escala in ((0.24, 0.07, 0.31), (0.07, 0.24, 0.31)):
                Entity(parent=self.modelo, model='cube', scale=escala, color=rgba(0.85, 0.08, 0.08, 1),
                       add_to_scene_entities=False)
        # Sin luz propia: siempre se distingue en la oscuridad (pero la niebla lo oculta de lejos)
        self.set_light_off(1)

    def actualizar(self, dt):
        """Devuelve False cuando ha caducado."""
        self.tiempo += dt
        self.modelo.rotation_y += 90 * dt
        self.modelo.y = 0.45 + 0.08 * math.sin(self.tiempo * 3)
        if self.tiempo > self.DURACION - 5:  # parpadea antes de desaparecer
            self.modelo.enabled = int(self.tiempo * 8) % 2 == 0
        return self.tiempo < self.DURACION
