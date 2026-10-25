"""La inflación de España (IPC del INE): descarga, caché sin red y rentabilidad real por año."""
import datetime as dt
import json
import os
import urllib.error
import urllib.parse
from unittest import mock

from comun import ConCarpeta, PreciosInventados, cartera, etf, mov
from test_red import RespuestaFalsa
from app import motor


def ine(meses_valores):
    """Respuesta de DATOS_SERIE del INE: una fila por mes con año, periodo (1-12) y valor."""
    filas = []
    for ym, v in meses_valores:
        ano, mes = int(ym[:4]), int(ym[5:])
        ts = int(dt.datetime(ano, mes, 1, tzinfo=dt.timezone(dt.timedelta(hours=1))).timestamp() * 1000)
        filas.append({"Fecha": ts, "FK_TipoDato": 1, "FK_Periodo": mes, "Anyo": ano, "Valor": v, "Secreto": False})
    cuerpo = {"COD": motor.IPC_SERIE, "Nombre": "Nacional. Índice general. Índice. ", "Data": filas}
    return RespuestaFalsa(json.dumps(cuerpo).encode())


def ipc_inventado(desde="2019-12", paso=0.003):
    """Un IPC que sube un 0,3 % cada mes, desde 'desde' hasta el mes en curso."""
    out, ano, mes, v = {}, int(desde[:4]), int(desde[5:]), 100.0
    hoy = dt.date.today()
    while (ano, mes) <= (hoy.year, hoy.month):
        out[f"{ano:04d}-{mes:02d}"] = round(v, 3)
        v *= 1 + paso
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return out


class DescargaIne(ConCarpeta):
    def setUp(self):
        super().setUp()
        motor.CACHE = os.path.join(self.carpeta, "cache")
        motor.SIN_RED, motor.SOLO_FALTAN = False, False
        self.urls = []

    def descarga(self, respuesta):
        def falso(req, timeout=None):
            self.urls.append(req.full_url)
            return respuesta
        with mock.patch("urllib.request.urlopen", falso):
            return motor.descargar_ipc()

    def test_lee_el_indice_mes_a_mes(self):
        ipc = self.descarga(ine([("2024-11", 98.1), ("2024-12", 98.411), ("2025-01", 98.579)]))
        self.assertEqual(ipc, {"2024-11": 98.1, "2024-12": 98.411, "2025-01": 98.579})

    def test_solo_pide_el_codigo_de_la_serie(self):
        self.descarga(ine([("2025-01", 98.579)]))
        self.assertEqual(len(self.urls), 1)
        partes = urllib.parse.urlsplit(self.urls[0])
        self.assertEqual((partes.scheme, partes.hostname), ("https", "servicios.ine.es"))
        self.assertEqual(partes.path, f"/wstempus/js/ES/DATOS_SERIE/{motor.IPC_SERIE}")
        self.assertEqual(urllib.parse.parse_qs(partes.query), {"nult": ["1000"]})

    def test_guarda_en_cache_y_fusiona(self):
        os.makedirs(motor.CACHE)
        ruta = os.path.join(motor.CACHE, f"INE_{motor.IPC_SERIE}.json")
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump({"2002-01": 58.717, "2025-01": 1.0}, f)
        ipc = self.descarga(ine([("2025-01", 98.579), ("2025-02", 98.9)]))
        self.assertEqual(ipc, {"2002-01": 58.717, "2025-01": 98.579, "2025-02": 98.9})
        with open(ruta, encoding="utf-8") as f:
            self.assertEqual(json.load(f), ipc)

    def test_sin_conexion_usa_la_cache(self):
        os.makedirs(motor.CACHE)
        with open(os.path.join(motor.CACHE, f"INE_{motor.IPC_SERIE}.json"), "w", encoding="utf-8") as f:
            json.dump({"2025-01": 98.579}, f)

        def caido(*a, **k):
            raise urllib.error.URLError("sin red")
        with mock.patch("urllib.request.urlopen", caido):
            self.assertEqual(motor.descargar_ipc(), {"2025-01": 98.579})

    def test_sin_red_no_sale_a_internet(self):
        os.makedirs(motor.CACHE)
        with open(os.path.join(motor.CACHE, f"INE_{motor.IPC_SERIE}.json"), "w", encoding="utf-8") as f:
            json.dump({"2025-01": 98.579}, f)
        motor.SIN_RED = True
        self.assertEqual(self.descarga(ine([("2025-02", 99.0)])), {"2025-01": 98.579})
        self.assertEqual(self.urls, [])

    def test_sin_conexion_ni_cache_devuelve_vacio_sin_avisos(self):
        def caido(*a, **k):
            raise urllib.error.URLError("sin red")
        with mock.patch("urllib.request.urlopen", caido):
            self.assertEqual(motor.descargar_ipc(), {})
        self.assertEqual(motor.AVISOS, [])

    def test_respuesta_rara_no_rompe_nada(self):
        self.assertEqual(self.descarga(RespuestaFalsa(b"<html>404</html>")), {})
        self.assertEqual(self.descarga(RespuestaFalsa(b'{"Data": [{"Anyo": 2025}]}')), {})


class InflacionDeUnPeriodo(ConCarpeta):
    IPC = {"2023-04": 99.0, "2023-05": 100.0, "2023-06": 103.0, "2023-12": 105.0,
           "2024-12": 108.15}

    def test_ano_completo_es_diciembre_contra_diciembre(self):
        self.assertAlmostEqual(motor.inflacion_entre(self.IPC, "2023-12-31", "2024-12-31"), 108.15 / 105 - 1)

    def test_periodo_parcial_interpola_dentro_del_mes(self):
        # El índice de cada mes vale para su último día: el 10 de junio está a 10/30 entre mayo y junio.
        self.assertAlmostEqual(motor.nivel_ipc(self.IPC, "2023-06-10"), 101.0)
        self.assertAlmostEqual(motor.inflacion_entre(self.IPC, "2023-06-10", "2023-06-30"), 103 / 101 - 1)

    def test_sin_el_mes_anterior_no_hay_dato(self):
        self.assertIsNone(motor.nivel_ipc(self.IPC, "2023-04-15"))
        self.assertIsNone(motor.inflacion_entre(self.IPC, "2023-04-15", "2023-06-30"))
        self.assertIsNone(motor.inflacion_entre({}, "2023-12-31", "2024-12-31"))

    def test_los_ultimos_dias_sin_publicar_usan_el_ultimo_mes(self):
        # El INE publica cada mes a mediados del siguiente: unas semanas sin dato se dan por planas.
        self.assertAlmostEqual(motor.nivel_ipc(self.IPC, "2025-01-20"), 108.15)
        # Pero con la caché muy atrasada no se inventa la inflación de meses enteros.
        self.assertIsNone(motor.nivel_ipc(self.IPC, "2025-04-20"))

    def test_rentabilidad_real(self):
        self.assertAlmostEqual(motor.rent_real(0.10, 0.03), 1.10 / 1.03 - 1)
        self.assertIsNone(motor.rent_real(0.10, None))
        self.assertIsNone(motor.rent_real(None, 0.03))


class RentabilidadRealPorAno(ConCarpeta):
    def construye(self, ipc):
        cfg = cartera([etf()], [mov("2023-06-01", "etf", "compra", 10, 1000)])
        with PreciosInventados(ipc=ipc):
            return motor.construir(cfg, self.carpeta, descargar=False)

    def test_ano_completo_y_parciales(self):
        ipc = ipc_inventado()
        D = self.construye(ipc)
        ra = D["rentabilidadAnual"]
        i24 = ra["anos"].index("2024")
        inf24 = ipc["2024-12"] / ipc["2023-12"] - 1
        self.assertAlmostEqual(ra["inflacion"][i24], inf24, places=4)
        # «cartera» va redondeada a 4 decimales y la real se calcula sin redondear.
        self.assertAlmostEqual(ra["real"][i24], (1 + ra["cartera"][i24]) / (1 + inf24) - 1, delta=2e-4)
        self.assertLess(ra["real"][i24], ra["cartera"][i24])

        # Primer año, incompleto: desde el primer día con cartera hasta el 31 de diciembre.
        i23 = ra["anos"].index("2023")
        self.assertTrue(ra["parcial"][i23])
        f0 = dt.date.fromisoformat(D["fechas"][0])
        self.assertEqual(f0.year, 2023)
        mes_ant = f"{f0.year}-{f0.month - 1:02d}"
        dias_mes = (dt.date(f0.year, f0.month % 12 + 1, 1) - dt.timedelta(days=1)).day
        nivel0 = ipc[mes_ant] + (ipc[f"{f0:%Y-%m}"] - ipc[mes_ant]) * f0.day / dias_mes
        inf23 = ipc["2023-12"] / nivel0 - 1
        self.assertAlmostEqual(ra["inflacion"][i23], inf23, places=4)
        self.assertAlmostEqual(ra["real"][i23], (1 + ra["cartera"][i23]) / (1 + inf23) - 1, delta=2e-4)

        # Último año, en curso: desde el 31 de diciembre hasta la fecha de los datos.
        self.assertTrue(ra["parcial"][-1])
        self.assertAlmostEqual(ra["inflacion"][-1],
                               motor.nivel_ipc(ipc, D["fechaExtracto"]) / ipc[f"{int(ra['anos'][-1]) - 1}-12"] - 1,
                               places=4)
        self.assertEqual(ra["ipcHasta"], max(ipc))

    def test_sin_ipc_no_hay_real_ni_errores(self):
        D = self.construye({})
        ra = D["rentabilidadAnual"]
        self.assertTrue(ra["anos"])
        self.assertEqual(ra["real"], [None] * len(ra["anos"]))
        self.assertEqual(ra["inflacion"], [None] * len(ra["anos"]))
        self.assertIsNone(ra["ipcHasta"])
        self.assertTrue(all(v is not None for v in ra["cartera"]))
        self.assertEqual(D["avisos"], [])

    def test_construir_sin_red_lee_el_ipc_guardado(self):
        cache = os.path.join(self.carpeta, "cache")
        os.makedirs(cache)
        with open(os.path.join(cache, f"INE_{motor.IPC_SERIE}.json"), "w", encoding="utf-8") as f:
            json.dump(ipc_inventado(), f)
        cfg = cartera([etf()], [mov("2023-06-01", "etf", "compra", 10, 1000)])
        with PreciosInventados(ipc_de_verdad=True):   # sin red: solo la caché
            D = motor.construir(cfg, self.carpeta, descargar=False)
        self.assertIsNotNone(D["rentabilidadAnual"]["real"][1])
