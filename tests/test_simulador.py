"""Simulador de venta con IRPF: qué lotes salen por FIFO, cuánto se gana y qué se pagaría."""
import datetime as dt
import os
from unittest import mock

from comun import ConCarpeta, cartera, etf, manual, mov
from app import almacen, servidor, simulador

HOY = dt.date(2026, 10, 25)


def fondo(pid, **extra):
    return etf(pid, "MS" + pid.upper(), tipo="fondo", **extra)


def simula(cfg, valores, **peticion):
    return simulador.simular(cfg, valores, hoy=HOY, **peticion)


def opcion(res, pid):
    return next(o for o in res["opciones"] if o["producto"] == pid)


class Tramos(ConCarpeta):
    def test_escala_del_ahorro(self):
        self.assertEqual(simulador.cuota_ahorro(0), 0)
        self.assertEqual(simulador.cuota_ahorro(-500), 0)
        self.assertEqual(simulador.cuota_ahorro(6000), 1140)                       # 19 %
        self.assertEqual(simulador.cuota_ahorro(50000), 1140 + 44000 * 0.21)       # 10.380
        self.assertEqual(simulador.cuota_ahorro(200000), 10380 + 150000 * 0.23)    # 44.880
        self.assertEqual(simulador.cuota_ahorro(300000), 44880 + 100000 * 0.27)    # 71.880
        self.assertAlmostEqual(simulador.cuota_ahorro(400000), 71880 + 100000 * 0.30)

    def test_compensacion_entre_ganancias_y_rendimientos_con_el_25(self):
        # Pérdidas de ventas: compensan dividendos e intereses hasta el 25 % de estos.
        self.assertEqual(simulador.base_ahorro(-1000, 2000), 1500)
        self.assertEqual(simulador.base_ahorro(-300, 2000), 1700)
        self.assertEqual(simulador.base_ahorro(500, 2000), 2500)
        self.assertEqual(simulador.base_ahorro(-500, 0), 0)


class VentaDeUnProducto(ConCarpeta):
    def setUp(self):
        super().setUp()
        self.cfg = cartera([etf("a")], [
            mov("2024-01-10", "a", "compra", 100, 1000),     # 10 €
            mov("2025-01-10", "a", "compra", 100, 1500),     # 15 €
        ])
        self.valores = {"a": 4000}                            # hoy, 20 € cada una

    def test_venta_parcial_por_fifo(self):
        res = simula(self.cfg, self.valores, producto="a", euros=3000)
        o = opcion(res, "a")
        self.assertTrue(o["alcanza"])
        self.assertAlmostEqual(o["unidades"], 150)
        self.assertEqual([l["fecha"] for l in o["lotes"]], ["2024-01-10", "2025-01-10"])   # lo más antiguo primero
        self.assertEqual([round(l["unidades"], 6) for l in o["lotes"]], [100, 50])
        self.assertEqual((o["coste"], o["ganancia"]), (1750, 1250))
        self.assertEqual(o["impuesto"], 237.5)                                             # 19 %
        self.assertEqual(res["mejor"], "a")
        self.assertIn("orientativ", res["aviso"])

    def test_en_participaciones_da_lo_mismo(self):
        res = simula(self.cfg, self.valores, producto="a", unidades="150")
        self.assertEqual(res["euros"], 3000)
        o = opcion(res, "a")
        self.assertEqual((o["coste"], o["ganancia"], o["impuesto"]), (1750, 1250, 237.5))

    def test_no_modifica_la_cartera(self):
        antes = repr(self.cfg)
        simula(self.cfg, self.valores, producto="a", euros=3000)
        self.assertEqual(repr(self.cfg), antes)

    def test_venta_superior_a_la_posicion_se_rechaza(self):
        with self.assertRaises(almacen.ErrorValidacion) as e:
            simula(self.cfg, self.valores, producto="a", euros=4500)
        self.assertIn("solo tienes", e.exception.errores[0])
        with self.assertRaises(almacen.ErrorValidacion) as e:
            simula(self.cfg, self.valores, producto="a", unidades=201)
        self.assertIn("solo tienes", e.exception.errores[0])
        with self.assertRaises(almacen.ErrorValidacion):
            simula(self.cfg, self.valores, producto="a", euros=0)
        with self.assertRaises(almacen.ErrorValidacion):
            simula(self.cfg, self.valores, euros="mucho")
        with self.assertRaises(almacen.ErrorValidacion):
            simula(self.cfg, self.valores, producto="no-existe", euros=10)

    def test_todo_cuando_sobran_decimales(self):
        o = opcion(simula(self.cfg, self.valores, producto="a", unidades=200.00001), "a")
        self.assertAlmostEqual(o["unidades"], 200)


class Perdidas(ConCarpeta):
    def test_venta_con_lotes_en_perdidas(self):
        cfg = cartera([etf("b")], [mov("2025-02-03", "b", "compra", 100, 2000)])   # a 20 €
        res = simula(cfg, {"b": 1500}, producto="b", euros=900)                    # hoy, a 15 €
        o = opcion(res, "b")
        self.assertEqual((o["coste"], o["ganancia"]), (1200, -300))
        self.assertEqual(o["impuesto"], 0)            # sin ganancias este año no hay nada que compensar
        self.assertIn("pérdidas", res["porque"])

    def test_la_perdida_compensa_lo_ganado_este_ano(self):
        cfg = cartera([etf("b"), etf("x", "X.DE")], [
            mov("2025-02-03", "b", "compra", 100, 2000),
            mov("2025-03-01", "x", "compra", 10, 1000),
            mov("2026-03-01", "x", "venta", 10, 2000),        # +1.000 ya realizados este año
        ])
        o = opcion(simula(cfg, {"b": 1500}, producto="b", euros=900), "b")
        self.assertEqual(o["impuesto"], -57)                    # te ahorras el 19 % de 300


class GananciasDelAno(ConCarpeta):
    def test_ganancia_que_cruza_un_tramo(self):
        cfg = cartera([etf("a"), etf("x", "X.DE")], [
            mov("2024-01-10", "a", "compra", 100, 500),       # a 5 €
            mov("2025-03-01", "x", "compra", 10, 1000),
            mov("2026-03-01", "x", "venta", 10, 6000),        # +5.000 ya realizados este año
        ])
        res = simula(cfg, {"a": 2500}, producto="a", euros=2500)   # todo, a 25 €: +2.000
        self.assertEqual(res["previo"]["ganancias"], 5000)
        o = opcion(res, "a")
        self.assertEqual(o["ganancia"], 2000)
        self.assertEqual(o["impuesto"], 1000 * 0.19 + 1000 * 0.21)   # 400: la mitad ya al 21 %
        self.assertEqual(o["tipoMarginal"], 0.21)

    def test_compensa_con_perdidas_ya_realizadas_este_ano(self):
        cfg = cartera([etf("a"), etf("x", "X.DE"), etf("y", "Y.DE")], [
            mov("2024-01-10", "a", "compra", 100, 500),       # a 5 €
            mov("2025-03-01", "x", "compra", 10, 3000),
            mov("2026-03-01", "x", "venta", 10, 2000),        # -1.000 este año
            mov("2024-03-01", "y", "compra", 10, 3000),
            mov("2025-06-01", "y", "venta", 10, 1000),        # -2.000, pero del año pasado: no cuenta
        ])
        res = simula(cfg, {"a": 2000}, producto="a", euros=2000)   # todo, a 20 €: +1.500
        self.assertEqual(res["previo"]["ganancias"], -1000)
        o = opcion(res, "a")
        self.assertEqual(o["ganancia"], 1500)
        self.assertEqual(o["impuesto"], 500 * 0.19)                # solo tributan 500

    def test_las_perdidas_compensan_dividendos_hasta_el_25(self):
        cfg = cartera([etf("a"), etf("x", "X.DE")], [
            mov("2024-01-10", "a", "compra", 100, 1000),      # a 10 €
            mov("2025-03-01", "x", "compra", 10, 3000),
            mov("2026-03-01", "x", "venta", 10, 2000),        # -1.000 este año...
            mov("2026-04-01", "x", "dividendo", 0, 2000),     # ...que solo compensan 500 (el 25 %) de esto
        ])
        res = simula(cfg, {"a": 4000}, producto="a", euros=2000)   # 50 a 40 €: +1.500
        self.assertEqual(res["previo"]["rendimientos"], 2000)
        self.assertEqual(res["previo"]["ganancias"], -1000)
        o = opcion(res, "a")
        self.assertEqual(o["ganancia"], 1500)
        # Antes: base 1.500 (2.000 - 500). Después: 500 de ventas + 2.000. Tributan 1.000 más, no 1.500.
        self.assertEqual(o["impuesto"], 1000 * 0.19)


class Comparacion(ConCarpeta):
    def setUp(self):
        super().setUp()
        self.productos = [etf("a"), etf("b", "B.DE"), etf("mon", "MON.DE", nombre="Monetario")]
        self.movs = [
            mov("2020-01-10", "a", "compra", 100, 1000),      # a 10 €; hoy a 40 €: mucha plusvalía
            mov("2025-02-03", "b", "compra", 100, 2000),      # a 20 €; hoy a 15 €: en pérdidas
            mov("2025-01-10", "mon", "compra", 100, 10000),   # a 100 €; hoy a 102 €: casi nada
        ]
        self.valores = {"a": 4000, "b": 1500, "mon": 10200}

    def test_elige_el_que_menos_impuestos_paga(self):
        res = simula(cartera(self.productos, self.movs), self.valores, producto="a", euros=1000)
        self.assertEqual(res["mejor"], "b")
        self.assertIn("pérdidas", res["porque"])
        self.assertEqual([o["producto"] for o in res["opciones"]], ["b", "mon", "a"])   # de menos a más impuestos
        self.assertEqual(res["ahorro"], opcion(res, "a")["impuesto"] - opcion(res, "b")["impuesto"])
        self.assertGreater(res["ahorro"], 0)

    def test_sin_perdidas_gana_el_monetario_por_su_poca_plusvalia(self):
        res = simula(cartera(self.productos, self.movs[:1] + self.movs[2:]), self.valores, producto="a", euros=1000)
        self.assertEqual(res["mejor"], "mon")
        self.assertIn("poca plusvalía", res["porque"])

    def test_el_que_no_llega_no_cuenta(self):
        res = simula(cartera(self.productos, self.movs), self.valores, producto="a", euros=3000)
        b = opcion(res, "b")
        self.assertFalse(b["alcanza"])                 # solo vale 1.500
        self.assertNotEqual(res["mejor"], "b")
        self.assertEqual(res["opciones"][-1]["producto"], "b")

    def test_participaciones_se_comparan_por_el_mismo_importe(self):
        res = simula(cartera(self.productos, self.movs), self.valores, producto="a", unidades=25)   # 25 × 40
        self.assertEqual(res["euros"], 1000)
        self.assertAlmostEqual(opcion(res, "mon")["unidades"], 1000 / 102)


class AvisosYProductos(ConCarpeta):
    def test_un_fondo_recuerda_el_traspaso(self):
        cfg = cartera([fondo("f")], [mov("2024-01-10", "f", "compra", 100, 1000)])
        o = opcion(simula(cfg, {"f": 2000}, producto="f", euros=500), "f")
        self.assertTrue(any("traspaso" in a for a in o["avisos"]), o["avisos"])
        cfg = cartera([etf("e")], [mov("2024-01-10", "e", "compra", 100, 1000)])
        o = opcion(simula(cfg, {"e": 2000}, producto="e", euros=500), "e")
        self.assertFalse(any("traspaso" in a for a in o["avisos"]))      # un ETF no se traspasa

    def test_planes_de_pensiones_fuera(self):
        cfg = cartera([etf("a"), etf("p", "P.DE", tipo="pension")], [
            mov("2024-01-10", "a", "compra", 100, 1000), mov("2024-01-10", "p", "compra", 100, 1000)])
        res = simula(cfg, {"a": 2000, "p": 2000}, euros=500)
        self.assertEqual([o["producto"] for o in res["opciones"]], ["a"])

    def test_producto_sin_unidades_se_vende_en_proporcion(self):
        cfg = cartera([manual("cart", tipo="otro")], [mov("2024-01-10", "cart", "compra", 0, 1000)])
        o = opcion(simula(cfg, {"cart": 2000}, producto="cart", euros=500), "cart")
        self.assertIsNone(o["unidades"])
        self.assertEqual((o["coste"], o["ganancia"]), (250, 250))

    def test_regla_de_los_dos_meses_si_compraste_hace_poco(self):
        cfg = cartera([etf("b"), etf("x", "X.DE")], [
            mov("2026-01-10", "b", "compra", 50, 1000),
            mov("2026-09-20", "b", "compra", 50, 1000),      # hace poco más de un mes
            mov("2025-03-01", "x", "compra", 10, 1000),
            mov("2026-03-01", "x", "venta", 10, 2000),        # +1.000 este año
        ])
        res = simula(cfg, {"b": 1500}, producto="b", euros=500)
        o = opcion(res, "b")
        self.assertLess(o["ganancia"], 0)
        self.assertTrue(any("dos meses" in a for a in o["avisos"]), o["avisos"])
        self.assertEqual(o["impuesto"], 0)            # esa pérdida aún no compensa: no ahorra nada
        self.assertIn("todavía", res["porque"])


class Endpoint(ConCarpeta):
    def setUp(self):
        super().setUp()
        cfg = cartera([etf("a")], [mov("2024-01-10", "a", "compra", 100, 1000)])
        almacen.guarda(os.path.join(self.carpeta, "cartera.json"), cfg)
        self.parche = mock.patch.object(servidor, "DATOS", self.carpeta)
        self.parche.start()
        servidor.escribe_json(servidor.ruta_calculado(), {"productos": [{"id": "a", "valor": 2000}]})
        self.web = servidor.app.test_client()

    def tearDown(self):
        self.parche.stop()
        super().tearDown()

    def test_simula_sin_guardar_nada(self):
        ruta = os.path.join(self.carpeta, "cartera.json")
        antes = os.path.getmtime(ruta), almacen.carga(ruta)
        j = self.web.get("/api/simular-venta?producto=a&euros=500").get_json()
        self.assertTrue(j["ok"], j)
        self.assertEqual(j["opciones"][0]["ganancia"], 250)
        self.assertEqual((os.path.getmtime(ruta), almacen.carga(ruta)), antes)

    def test_errores(self):
        r = self.web.get("/api/simular-venta?producto=a&euros=5000")
        self.assertEqual(r.status_code, 400)
        self.assertIn("solo tienes", r.get_json()["errores"][0])
        with mock.patch.object(servidor, "modo", lambda: "todos"):
            r = self.web.get("/api/simular-venta?producto=a&euros=100")
        self.assertEqual(r.status_code, 400)
        self.assertIn("cada persona", r.get_json()["errores"][0])
