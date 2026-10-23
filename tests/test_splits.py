"""Splits de acciones y ETFs: Yahoo ajusta hacia atrás los precios, pero tus movimientos
guardan las participaciones que te dio el broker. El motor las pasa a participaciones de
después del split al calcular (sin tocar cartera.json) y no ajusta dos veces si ya lo hiciste tú."""
import copy
import os
import unittest
from unittest import mock

from comun import ConCarpeta, PreciosInventados, cartera, etf, guarda_cache_yahoo, mov, serie_inventada
from app import almacen, fiscal, motor, servidor

SPLIT = "2025-03-03"            # ex-date: ese día ya cotiza con las participaciones nuevas
SPLITS = {SPLIT: 4.0}           # 4 nuevas por cada 1 antigua
# Cierres como los da Yahoo: ajustados al split (antes del split el precio real era 4 veces este).
SERIE = serie_inventada(base=25, desde="2024-01-01", paso=0.0003)
SERIE_B = serie_inventada(base=20, desde="2024-01-01", paso=0)

ANTES, DESPUES, VENTA = "2024-01-02", "2025-06-02", "2025-09-01"
IMP_ANTES = round(2 * 4 * SERIE[ANTES], 2)        # 2 participaciones antiguas a su precio real
IMP_DESPUES = round(8 * SERIE[DESPUES], 2)        # 8 participaciones nuevas
IMP_VENTA = round(16 * SERIE[VENTA], 2)


def compras(unidades_antes):
    return [mov(ANTES, "etf", "compra", unidades_antes, IMP_ANTES, mid="c1"),
            mov(DESPUES, "etf", "compra", 8, IMP_DESPUES, mid="c2")]


class ConSplit(ConCarpeta):
    def setUp(self):
        super().setUp()
        self.cache = guarda_cache_yahoo(self.carpeta, "TEST.DE", SERIE, SPLITS)

    def construye(self, cfg):
        with PreciosInventados({"TEST.DE": SERIE, "OTRO.DE": SERIE_B}):
            return motor.construir(cfg, self.carpeta, descargar=False)


class AjustaSplits(ConSplit):
    """La función que pasa las participaciones de antes del split a las de después."""

    def ajusta(self, movs, **kw):
        return motor.ajusta_splits(movs, [etf()], cache=self.cache, **kw)

    def test_compra_antes_del_split_en_participaciones_del_broker(self):
        movs = compras(2)
        nuevos, resumen = self.ajusta(movs)
        self.assertAlmostEqual(nuevos[0]["unidades"], 8)
        self.assertAlmostEqual(nuevos[1]["unidades"], 8)
        self.assertEqual(movs[0]["unidades"], 2)          # el original no se toca
        self.assertEqual(resumen["etf"]["movimientos"], 1)
        self.assertEqual(resumen["etf"]["splits"], {SPLIT: 4.0})

    def test_ya_corregida_a_mano_no_se_ajusta_dos_veces(self):
        nuevos, resumen = self.ajusta(compras(8))
        self.assertAlmostEqual(nuevos[0]["unidades"], 8)
        self.assertEqual(resumen, {})

    def test_el_dia_del_split_ya_es_despues(self):
        nuevos, _ = self.ajusta([mov(SPLIT, "etf", "compra", 1, round(4 * SERIE[SPLIT], 2))])
        self.assertAlmostEqual(nuevos[0]["unidades"], 1)

    def test_sin_importe_o_sin_precio_se_supone_del_broker(self):
        nuevos, _ = self.ajusta([mov("2024-06-03", "etf", "ajuste", 3, 0),
                                 mov("2023-01-02", "etf", "compra", 1, 100)])   # sin cierres antes de 2024
        self.assertAlmostEqual(nuevos[0]["unidades"], 12)
        # Sin cierre ese día se compara con el primero que hay (25 ≈ 100 / 4): se ajusta.
        self.assertAlmostEqual(nuevos[1]["unidades"], 4)

    def test_dividendos_y_comisiones_no_se_tocan(self):
        movs = [mov("2024-06-03", "etf", "dividendo", 0, 5), mov("2024-06-03", "etf", "comision", 0, 1)]
        nuevos, resumen = self.ajusta(movs)
        self.assertEqual(nuevos, movs)
        self.assertEqual(resumen, {})

    def test_hasta_una_fecha_da_las_participaciones_de_ese_dia(self):
        nuevos, _ = self.ajusta(compras(2)[:1], hasta="2024-06-03")
        self.assertAlmostEqual(nuevos[0]["unidades"], 2)
        nuevos, _ = self.ajusta(compras(8)[:1], hasta="2024-06-03")   # corregida a mano: vuelve a las del broker
        self.assertAlmostEqual(nuevos[0]["unidades"], 2)

    def test_sin_fichero_de_splits_no_cambia_nada(self):
        movs = [mov(ANTES, "x", "compra", 2, 9999)]
        nuevos, resumen = motor.ajusta_splits(movs, [etf("x", "SINSPLITS.DE")], cache=self.cache)
        self.assertEqual(nuevos, movs)
        self.assertEqual(resumen, {})

    def test_solo_productos_de_yahoo(self):
        p = {**etf(), "fuente": "morningstar"}
        nuevos, _ = motor.ajusta_splits(compras(2), [p], cache=self.cache)
        self.assertEqual(nuevos[0]["unidades"], 2)


class Construir(ConSplit):
    def test_participaciones_valor_y_rentabilidad(self):
        D = self.construye(cartera([etf()], compras(2)))
        p = D["productos"][0]
        self.assertAlmostEqual(p["participaciones"], 16)
        self.assertAlmostEqual(p["valor"], 16 * SERIE[p["navFecha"]], places=2)
        self.assertAlmostEqual(p["aportado"], IMP_ANTES + IMP_DESPUES, places=2)
        rent = D["rentabilidadAnual"]
        for ano, r in zip(rent["anos"], rent["porProducto"]["etf"]):
            with self.subTest(ano=ano):
                self.assertGreater(r, 0)          # sube un poco cada día: nada de -75 %
                self.assertLess(r, 0.15)
        self.assertEqual(p["aportaciones"][0]["participaciones"], 8)

    def test_corregida_a_mano_da_lo_mismo(self):
        D1 = self.construye(cartera([etf()], compras(2)))
        D2 = self.construye(cartera([etf()], compras(8)))
        p1, p2 = D1["productos"][0], D2["productos"][0]
        for k in ("participaciones", "valor", "aportado", "plusvalia"):
            with self.subTest(campo=k):
                self.assertAlmostEqual(p1[k], p2[k], places=6)
        self.assertEqual(D1["rentabilidadAnual"]["porProducto"], D2["rentabilidadAnual"]["porProducto"])
        self.assertFalse(any("split" in a for a in D2["avisos"]))

    def test_avisa_de_los_movimientos_ajustados(self):
        D = self.construye(cartera([etf()], compras(2)))
        avisos = [a for a in D["avisos"] if "split" in a]
        self.assertEqual(len(avisos), 1, D["avisos"])
        self.assertIn("split de 4 por 1 el 03/03/2025", avisos[0])
        self.assertIn("1 movimiento anterior", avisos[0])

    def test_venta_de_todo_despues_del_split(self):
        cfg = cartera([etf()], compras(2) + [mov(VENTA, "etf", "venta", 16, IMP_VENTA, mid="v1")])
        D = self.construye(cfg)
        p = D["productos"][0]
        self.assertAlmostEqual(p["participaciones"], 0)
        self.assertAlmostEqual(p["realizado"], IMP_VENTA - IMP_ANTES - IMP_DESPUES, places=2)
        self.assertFalse(any("vendes más" in a for a in D["avisos"]), D["avisos"])

    def test_no_reescribe_la_cartera(self):
        cfg = cartera([etf()], compras(2))
        antes = copy.deepcopy(cfg)
        self.construye(cfg)
        self.assertEqual(cfg, antes)

    def test_traspaso_hacia_un_producto_con_split(self):
        # De OTRO.DE (sin split) a TEST.DE antes del split: entran participaciones antiguas.
        f = "2024-06-03"
        raw = round(200 / (4 * SERIE[f]), 6)
        for unidades_destino, esperadas in ((raw, 4 * raw), (4 * raw, 4 * raw)):   # del broker y corregidas
            with self.subTest(unidades_destino=unidades_destino):
                cfg = cartera([etf(), etf("b", "OTRO.DE")], [
                    mov(ANTES, "b", "compra", 10, 200, mid="cb"),
                    {"id": "t1", "fecha": f, "producto": "b", "destino": "etf", "tipo": "traspaso",
                     "unidades": 10, "unidadesDestino": unidades_destino, "importe": 200}])
                est, _, _ = motor.fifo_cartera(cfg, cache=self.cache)
                self.assertAlmostEqual(sum(e[1] for e in est["etf"]["eventos"]), esperadas, places=5)
                self.assertAlmostEqual(sum(e[1] for e in est["b"]["eventos"]), 0)
                self.assertAlmostEqual(almacen.unidades_a(cfg, "etf", DESPUES, cache=self.cache), esperadas, places=5)
                self.assertAlmostEqual(almacen.unidades_a(cfg, "etf", f, cache=self.cache), raw, places=5)

    def test_traspaso_de_todo_despues_del_split(self):
        cfg = cartera([etf(), etf("b", "OTRO.DE")], compras(2) + [
            {"id": "t1", "fecha": VENTA, "producto": "etf", "destino": "b", "tipo": "traspaso",
             "unidades": 16, "unidadesDestino": IMP_VENTA / 20, "importe": IMP_VENTA}])
        D = self.construye(cfg)
        self.assertFalse(any("traspasas más" in a for a in D["avisos"]), D["avisos"])
        b = next(p for p in D["productos"] if p["id"] == "b")
        self.assertAlmostEqual(b["aportado"], IMP_ANTES + IMP_DESPUES, places=2)   # el coste pasa entero

    def test_lotes_vivos(self):
        lotes = motor.lotes_vivos(cartera([etf()], compras(2)), "etf", DESPUES, cache=self.cache)
        self.assertEqual([round(l[0], 6) for l in lotes], [8, 8])
        lotes = motor.lotes_vivos(cartera([etf()], compras(2)), "etf", "2024-06-03", cache=self.cache)
        self.assertEqual([round(l[0], 6) for l in lotes], [2])


class Renta(ConSplit):
    def setUp(self):
        super().setUp()
        self.cfg = cartera([etf()], compras(2) + [mov(VENTA, "etf", "venta", 16, IMP_VENTA, mid="v1")])

    def test_venta_despues_del_split(self):
        inf = fiscal.informe(self.cfg, "2025", cache=self.cache)
        v = inf["ventas"][0]
        self.assertAlmostEqual(v["unidades"], 16)
        self.assertEqual([c["unidades"] for c in v["compras"]], [8, 8])
        self.assertEqual([c["fecha"] for c in v["compras"]], [ANTES, DESPUES])
        self.assertAlmostEqual(v["adquisicion"], IMP_ANTES + IMP_DESPUES, places=2)
        self.assertAlmostEqual(v["ganancia"], IMP_VENTA - IMP_ANTES - IMP_DESPUES, places=2)
        self.assertEqual(v["avisos"], [])

    def test_en_la_app_con_la_cache_compartida(self):
        almacen.guarda(os.path.join(self.carpeta, "cartera.json"), self.cfg)
        with mock.patch.object(servidor, "DATOS", self.carpeta), mock.patch.object(motor, "CACHE", "no_existe"):
            web = servidor.app.test_client()
            j = web.get("/api/fiscal?ano=2025").get_json()
            self.assertAlmostEqual(j["ventas"][0]["unidades"], 16)
            j = web.get(f"/api/unidades?producto=etf&fecha={DESPUES}").get_json()
            self.assertAlmostEqual(j["unidades"], 16)


class VenderTodo(ConSplit):
    def test_unidades_a_despues_del_split(self):
        for antes in (2, 8):   # del broker y corregidas a mano
            with self.subTest(antes=antes):
                cfg = cartera([etf()], compras(antes))
                self.assertAlmostEqual(almacen.unidades_a(cfg, "etf", DESPUES, cache=self.cache), 16)
                self.assertAlmostEqual(almacen.unidades_a(cfg, "etf", "2024-06-03", cache=self.cache), 2)

    def test_vender_todo_despues_del_split_se_valida_bien(self):
        cfg = cartera([etf()], compras(2))
        with mock.patch.object(motor, "CACHE", self.cache):
            m = almacen.guarda_movimiento(cfg, {"producto": "etf", "tipo": "venta", "fecha": VENTA,
                                                "unidades": "16", "importe": str(IMP_VENTA)})
        self.assertEqual(m["unidades"], 16)


if __name__ == "__main__":
    unittest.main()
