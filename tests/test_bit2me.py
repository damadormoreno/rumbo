"""Extractos de Bit2Me («summary-AAAA.xlsx»): staking, compras, ventas, permutas y depósitos, sin duplicar al reimportar.

Los extractos son sintéticos: misma estructura que los de verdad, con cifras y UUID inventados."""
import io
import os
import unittest
from unittest import mock

from openpyxl import Workbook

from comun import ConCarpeta, PreciosInventados, cartera, mov, serie_inventada
from app import almacen, importar, plantilla, servidor

# Así viene la cabecera en los extractos descargados: las tildes llegan rotas.
CAB = ["Tipo de operaci�n", "Cantidad de destino", "Moneda de destino", "Cantidad de origen", "Moneda de origen",
       "Comisi�n de la operaci�n", "Moneda de la comisi�n", "Exchange", "Grupo", "Descripci�n",
       "Fecha", "Tipo de cambio"]

PRECIOS = {"BTC-EUR": serie_inventada(base=60000, desde="2023-01-02", paso=0),
           "LTC-EUR": serie_inventada(base=80, desde="2023-01-02", paso=0),
           "CG:stablr-euro": serie_inventada(base=1, desde="2023-01-02", paso=0),
           "CG:eurod": serie_inventada(base=1, desde="2023-01-02", paso=0)}


def uuid(n):
    return f"{n:08x}-1111-4222-8333-444444444444"


def fila(n, tipo, grupo, fecha, destino=None, mdest=None, origen=None, morig=None, comision=0, mcom=None,
         cambio=None, extra=""):
    return [tipo, destino, mdest, origen, morig, comision, mcom or mdest, "Bit2Me", grupo, uuid(n) + extra,
            fecha, cambio]


def recompensa(n, fecha, unidades, moneda="BTC"):
    return fila(n, "Staking", "earn", fecha, unidades, moneda)


def extracto(filas, cabecera=CAB):
    libro = Workbook()
    hoja = libro.active
    hoja.title = "1"
    hoja.append([" "])
    hoja.append(cabecera)
    for f in filas:
        hoja.append(f)
    buf = io.BytesIO()
    libro.save(buf)
    return buf.getvalue()


def cripto(pid, ident, fuente="yahoo", codigo=None):
    return {"id": pid, "nombre": ident, "corto": ident, "tipo": "cripto", "fuente": fuente,
            "codigo": codigo or f"{ident}-EUR", "identificador": ident, "moneda": "EUR", "slot": 1}


def productos():
    return [cripto("btc", "BTC"), cripto("ltc", "LTC"), cripto("eurr", "EURR", "coingecko", "stablr-euro"),
            cripto("eurod", "EUROD", "coingecko", "eurod"),
            {**cripto("b2m", "B2M", "manual"), "codigo": ""}]


class Base(ConCarpeta):
    def setUp(self):
        super().setUp()
        self.cfg = cartera(productos())
        self.precios = PreciosInventados(PRECIOS)
        self.precios.__enter__()
        self.addCleanup(self.precios.__exit__)

    def plan(self, *extractos, cfg=None):
        archivos = [(f"summary-{2024 + i}.xlsx", extracto(e)) for i, e in enumerate(extractos)]
        return importar.preparar_bit2me(cfg or self.cfg, archivos, self.carpeta)

    def importa(self, *extractos, cfg=None):
        cfg = cfg or self.cfg
        return importar.aplicar(cfg, self.plan(*extractos, cfg=cfg))

    def movs(self, tipo=None):
        return [m for m in self.cfg["movimientos"] if tipo in (None, m["tipo"])]


class Deteccion(unittest.TestCase):
    def test_cabecera_con_tildes_rotas(self):
        self.assertTrue(importar.es_bit2me("summary-2025.xlsx", extracto([])))

    def test_cabecera_con_tildes_bien_o_mal_convertidas(self):
        bien = [c.replace("�", "ó") for c in CAB]
        self.assertTrue(importar.es_bit2me("summary-2025.xlsx", extracto([], bien)))
        mal = [c.replace("�", "Ã³") for c in CAB]
        self.assertTrue(importar.es_bit2me("summary-2025.xlsx", extracto([], mal)))

    def test_la_plantilla_y_un_csv_no_son_de_bit2me(self):
        self.assertFalse(importar.es_bit2me("plantilla.xlsx", plantilla.excel()))
        self.assertFalse(importar.es_bit2me("summary-2025.csv", b"fecha;importe\n"))
        self.assertFalse(importar.es_bit2me("roto.xlsx", b"no es un excel"))


class Staking(Base):
    def test_recompensa_sin_importe(self):
        inf = self.importa([recompensa(1, "2025-03-10 08:15", 0.00000037)])
        self.assertEqual(inf["errores"], [])
        m = self.movs()[0]
        self.assertEqual((m["tipo"], m["producto"], m["fecha"], m["unidades"]), ("staking", "btc", "2025-03-10", 0.00000037))
        self.assertNotIn("importe", m)
        self.assertEqual(inf["totales"]["stakingSinValorar"], 1)

    def test_muchas_recompensas_iguales_el_mismo_dia(self):
        filas = [recompensa(i, "2025-03-10 00:00", 1.5, "B2M") for i in range(40)]
        self.assertEqual(self.importa(filas)["añadidos"], 40)
        inf = self.importa(filas)
        self.assertEqual((inf["añadidos"], inf["repetidos"]), (0, 40))
        self.assertEqual(len(self.movs("staking")), 40)

    def test_recompensas_ya_importadas_con_la_plantilla_no_se_duplican(self):
        # Antes se importaban con la plantilla o la IA, sin UUID: cada una guardada cubre a una sola.
        self.cfg["movimientos"] = [{**mov("2025-03-10", "b2m", "staking", 1.5, None, mid=f"m{i}"), "origen": "importado"}
                                   for i in range(30)]
        for m in self.cfg["movimientos"]:
            m.pop("importe")
        inf = self.importa([recompensa(i, "2025-03-10 00:00", 1.5, "B2M") for i in range(40)])
        self.assertEqual((inf["añadidos"], inf["repetidos"]), (10, 30))


class ComprasYVentas(Base):
    def test_compra_con_comision_en_euros(self):
        # «pocket»: la comisión sale de los euros pagados; lo recibido ya es neto.
        inf = self.importa([fila(1, "Trade", "pocket", "2025-02-03 10:00", 198.1, "B2M", 100, "EUR", 0.95, "EUR", 0.5)])
        self.assertEqual(inf["errores"], [])
        m = self.movs()[0]
        self.assertEqual((m["tipo"], m["producto"], m["unidades"], m["importe"], m["comision"]),
                         ("compra", "b2m", 198.1, 100, 0.95))

    def test_compra_con_comision_en_la_cripto(self):
        # «trading»: la comisión se descuenta de lo recibido y se valora al precio de la operación.
        self.importa([fila(1, "Trade", "trading", "2025-02-03 10:00", 0.01, "BTC", 600, "EUR", 0.00006, "BTC", 60000)])
        m = self.movs()[0]
        self.assertEqual((m["tipo"], m["unidades"], m["importe"], m["comision"]), ("compra", 0.00994, 600, 3.6))

    def test_venta_a_euros(self):
        inf = self.importa([fila(1, "Trade", "trading", "2025-02-03 10:00", 50, "EUROD", 50, "EUR", 0.3, "EUROD", 1),
                            fila(2, "Trade", "trading", "2025-02-04 10:00", 49.68, "EUR", 49.7, "EUROD", 0.3, "EUR", 1)])
        self.assertEqual(inf["errores"], [])
        compra, venta = self.movs()
        self.assertEqual(compra["unidades"], 49.7)
        self.assertEqual((venta["tipo"], venta["producto"], venta["unidades"], venta["importe"], venta["comision"]),
                         ("venta", "eurod", 49.7, 49.38, 0.3))

    def test_pago_con_tarjeta_suma_su_comision_a_la_compra(self):
        # El depósito con tarjeta y la compra que paga llevan el mismo UUID.
        inf = self.importa([fila(1, "Deposit", "card", "2025-02-03 10:00", 100, "EUR", 102, "EUR", 2, "EUR"),
                            fila(1, "Trade", "pocket", "2025-02-03 10:00", 198.1, "B2M", 100, "EUR", 0.95, "EUR", 0.5)])
        self.assertEqual(inf["errores"], [])
        m = self.movs()[0]
        self.assertEqual((m["importe"], m["comision"], m["unidades"]), (102, 2.95, 198.1))


class Permutas(Base):
    def test_permuta_es_una_venta_y_una_compra_al_precio_del_dia(self):
        inf = self.importa([fila(1, "Trade", "trading", "2025-02-03 10:00", 1.006, "LTC", 80.48, "EUR", 0.006, "LTC", 80),
                            fila(2, "Trade", "pocket", "2025-05-05 10:00", 79.24, "EURR", 1, "LTC", 0.0095, "LTC", 80)])
        self.assertEqual(inf["errores"], [])
        venta = next(m for m in self.movs("venta"))
        compra = next(m for m in self.movs("compra") if m["producto"] == "eurr")
        # 1 LTC a 80 €: la comisión (0,0095 LTC) se cobra en la venta y no se cuenta dos veces.
        self.assertEqual((venta["producto"], venta["unidades"], venta["importe"], venta["comision"]),
                         ("ltc", 1, 79.24, 0.76))
        self.assertEqual((compra["unidades"], compra["importe"], compra.get("comision")), (79.24, 79.24, None))
        self.assertEqual(almacen.unidades_a(self.cfg, "ltc", "2025-12-31"), 0)

    def test_permuta_valorada_con_la_moneda_que_cotiza(self):
        # B2M se valora a mano: el valor de mercado sale del BTC recibido.
        inf = self.importa([fila(1, "Trade", "pocket", "2025-02-03 10:00", 2000, "B2M", 200, "EUR", 0, "EUR", 0.1),
                            fila(2, "Trade", "pocket", "2025-05-05 10:00", 0.001, "BTC", 1000, "B2M", 0, "B2M", 0.00000001)])
        self.assertEqual(inf["errores"], [])
        venta = self.movs("venta")[0]
        compra = next(m for m in self.movs("compra") if m["producto"] == "btc")
        self.assertEqual((venta["producto"], venta["unidades"], venta["importe"]), ("b2m", 1000, 60))
        self.assertEqual((compra["unidades"], compra["importe"]), (0.001, 60))

    def test_permuta_sin_precio_de_ninguna_de_las_dos_da_error(self):
        self.cfg["productos"].append({**cripto("sol2", "SOL2", "manual"), "codigo": ""})
        inf = self.importa([fila(1, "Trade", "pocket", "2025-02-03 10:00", 2000, "B2M", 200, "EUR", 0, "EUR", 0.1),
                            fila(2, "Trade", "pocket", "2025-05-05 10:00", 3, "SOL2", 1000, "B2M", 0, "B2M", 0.003)])
        self.assertEqual(len(self.movs()), 1)
        self.assertEqual(len(inf["errores"]), 1)
        self.assertIn("fila 4", inf["errores"][0]["fila"])
        self.assertIn("precio", inf["errores"][0]["mensaje"])


class Depositos(Base):
    def test_euros_que_entran_y_salen_no_son_movimientos(self):
        inf = self.importa([fila(1, "Deposit", "bank-transfer", "2025-02-03 10:00", 500, "EUR", 500, "EUR"),
                            fila(2, "Deposit", "card", "2025-02-04 10:00", 100, "EUR", 100, "EUR"),
                            fila(3, "Withdrawal", "bank-transfer", "2025-02-05 10:00", 50, "EUR", 50, "EUR")])
        self.assertEqual((inf["añadidos"], inf["errores"], self.movs()), (0, [], []))
        aviso = next(a for a in inf["avisos"] if "euros" in a)
        self.assertIn("2 ingresos", aviso)
        self.assertIn("1 retirada", aviso)

    def test_cripto_que_llega_por_blockchain_no_inventa_coste(self):
        inf = self.importa([fila(1, "Deposit", "blockchain", "2025-02-03 10:00", 0.5, "BTC", 0.5, "BTC",
                                 extra=" tx_hash:abc123")])
        self.assertFalse(any(m.get("importe") for m in self.movs()))
        self.assertTrue(any("blockchain" in a for a in inf["avisos"]))


class Reimportar(Base):
    FILAS = [fila(1, "Trade", "pocket", "2024-02-03 10:00", 198.1, "B2M", 100, "EUR", 0.95, "EUR", 0.5),
             recompensa(2, "2024-02-04 00:00", 0.5, "B2M"),
             recompensa(3, "2024-12-30 00:00", 0.5, "B2M"),
             recompensa(4, "2025-01-02 00:00", 0.5, "B2M"),
             fila(5, "Trade", "trading", "2025-02-03 10:00", 0.01, "BTC", 600, "EUR", 0.00006, "BTC", 60000),
             recompensa(6, "2025-02-04 00:00", 0.0000001)]

    def test_el_mismo_extracto_dos_veces(self):
        self.assertEqual(self.importa(self.FILAS)["añadidos"], 6)
        inf = self.importa(self.FILAS)
        self.assertEqual((inf["añadidos"], inf["repetidos"]), (0, 6))
        self.assertEqual(len(self.movs()), 6)

    def test_dos_años_que_se_solapan_a_la_vez(self):
        inf = self.importa(self.FILAS[:4], self.FILAS[2:])
        self.assertEqual((inf["añadidos"], inf["repetidos"]), (6, 2))
        self.assertEqual(len(self.movs()), 6)

    def test_dos_años_que_se_solapan_uno_detras_de_otro(self):
        self.importa(self.FILAS[:4])
        inf = self.importa(self.FILAS[2:])
        self.assertEqual((inf["añadidos"], inf["repetidos"]), (2, 2))
        self.assertEqual(len(self.movs()), 6)

    def test_la_vista_previa_no_toca_la_cartera(self):
        antes = [dict(m) for m in self.cfg["movimientos"]]
        importar.vista_previa(self.cfg, self.plan(self.FILAS))
        self.assertEqual(self.cfg["movimientos"], antes)


class MonedasSinCotizacion(Base):
    def test_moneda_que_no_existe_ni_cotiza_da_error_en_cada_fila(self):
        with mock.patch.object(importar.buscar, "buscar", lambda q: []):
            inf = self.importa([recompensa(1, "2025-03-10 00:00", 0.0002, "SOL2"),
                                recompensa(2, "2025-03-11 00:00", 0.0002, "SOL2")])
        self.assertEqual(inf["añadidos"], 0)
        self.assertEqual([e["fila"] for e in inf["errores"]], ["summary-2024.xlsx · fila 3", "summary-2024.xlsx · fila 4"])
        self.assertIn("«SOL2»", inf["errores"][0]["mensaje"])
        self.assertIn("Valor anotado a mano", inf["errores"][0]["mensaje"])

    def test_moneda_valorada_a_mano_se_importa(self):
        inf = self.importa([recompensa(1, "2025-03-10 00:00", 1.25, "B2M"),
                            fila(2, "Trade", "pocket", "2025-03-11 10:00", 198.1, "B2M", 100, "EUR", 0.95, "EUR", 0.5)])
        self.assertEqual((inf["añadidos"], inf["errores"]), (2, []))
        self.assertAlmostEqual(almacen.unidades_a(self.cfg, "b2m", "2025-12-31"), 199.35, places=8)

    def test_moneda_nueva_se_busca_como_cripto(self):
        cands = [{"fuente": "morningstar", "codigo": "F0000X", "nombre": "Un fondo", "tipo": "fondo", "moneda": "EUR"},
                 {"fuente": "coingecko", "codigo": "ripple", "nombre": "XRP", "tipo": "cripto", "moneda": "EUR"}]
        cfg = cartera()
        with mock.patch.object(importar.buscar, "buscar", lambda q: cands):
            inf = self.importa([recompensa(1, "2025-03-10 00:00", 0.25, "XRP")], cfg=cfg)
        self.assertEqual(inf["errores"], [])
        self.assertEqual((cfg["productos"][0]["tipo"], cfg["productos"][0]["identificador"]), ("cripto", "XRP"))


class EnLaApp(ConCarpeta):
    def test_se_reconoce_al_subirlo_como_plantilla(self):
        datos = extracto([recompensa(1, "2025-03-10 00:00", 0.00000037),
                          fila(2, "Deposit", "bank-transfer", "2025-02-03 10:00", 500, "EUR", 500, "EUR")])
        with mock.patch.object(servidor, "DATOS", self.carpeta), PreciosInventados(PRECIOS):
            almacen.guarda(os.path.join(self.carpeta, "cartera.json"), cartera([cripto("btc", "BTC")]))
            web = servidor.app.test_client()
            for origen in ("plantilla", "bit2me"):
                j = web.post("/api/importar/previsualizar", content_type="multipart/form-data",
                             data={"origen": origen, "archivos": (io.BytesIO(datos), "summary-2025.xlsx")}).get_json()
                self.assertTrue(j["ok"], j)
                self.assertEqual(j["informe"]["totales"]["numStaking"], 1)
            j = web.post("/api/importar/confirmar", json={"token": j["token"]}).get_json()
            self.assertTrue(j["ok"], j)
            movs = web.get("/api/cartera").get_json()["cartera"]["movimientos"]
            self.assertEqual([m["tipo"] for m in movs], ["staking"])


if __name__ == "__main__":
    unittest.main()
