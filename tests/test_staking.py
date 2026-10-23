"""Recompensas de staking: unidades que entran sin dinero tuyo, con o sin lo que valían al recibirlas."""
import unittest
from decimal import Decimal
from unittest import mock

from comun import ConCarpeta, PreciosInventados, cartera, mov, serie_inventada
from app import almacen, exportar, fiscal, importar, motor, plantilla

CAB = "fecha;identificador;nombre;tipo_producto;tipo_movimiento;unidades;importe;moneda;comision;nota"


def btc(pid="btc", **extra):
    return {"id": pid, "nombre": "Bitcoin", "corto": "Bitcoin", "tipo": "cripto", "fuente": "yahoo",
            "codigo": "BTC-EUR", "identificador": "BTC", "moneda": "EUR", "slot": 1, **extra}


def staking(fecha, unidades, importe=None, producto="btc", mid=None):
    m = mov(fecha, producto, "staking", unidades, importe, mid=mid)
    if importe is None:
        m.pop("importe")
    return m


def importa(cfg, filas, carpeta):
    """Importa las filas (sin la cabecera) sobre cfg y devuelve el informe."""
    tabla, error = importar.leer_tabla("x.csv", (CAB + "\n" + "\n".join(filas) + "\n").encode())
    assert not error, error
    return importar.aplicar(cfg, importar.preparar_tabla(cfg, tabla, carpeta))


class Guardar(unittest.TestCase):
    def setUp(self):
        self.cfg = cartera([btc(), {"id": "etf", "nombre": "ETF", "tipo": "etf", "fuente": "yahoo", "codigo": "X.DE"}])

    def test_sin_importe_no_se_inventa_ninguno(self):
        m = almacen.guarda_movimiento(self.cfg, {"tipo": "staking", "producto": "btc", "fecha": "2026-01-05",
                                                 "unidades": "0,00000037"})
        self.assertEqual(m["unidades"], 0.00000037)
        self.assertNotIn("importe", m)
        self.assertEqual(m["tipo"], "staking")

    def test_con_valoracion_guarda_lo_que_valia_con_sus_decimales(self):
        m = almacen.guarda_movimiento(self.cfg, {"tipo": "staking", "producto": "btc", "fecha": "2026-01-05",
                                                 "unidades": "0,00000037", "importe": "0,0222", "nota": "Bit2Me"})
        self.assertEqual(m["importe"], 0.0222)   # con 2 decimales serían 0,02: un 10 % menos
        self.assertEqual(m["nota"], "Bit2Me")

    def test_unidades_negativas_cero_o_ausentes(self):
        for u in ("-0,5", "0", "", None, "0,000000001"):
            with self.subTest(unidades=u), self.assertRaises(almacen.ErrorValidacion):
                almacen.guarda_movimiento(self.cfg, {"tipo": "staking", "producto": "btc", "fecha": "2026-01-05",
                                                     "unidades": u})

    def test_solo_en_criptomonedas_y_con_fecha(self):
        with self.assertRaises(almacen.ErrorValidacion) as e:
            almacen.guarda_movimiento(self.cfg, {"tipo": "staking", "producto": "etf", "fecha": "2026-01-05",
                                                 "unidades": "1"})
        self.assertIn("criptomoneda", " ".join(e.exception.errores))
        with self.assertRaises(almacen.ErrorValidacion):
            almacen.guarda_movimiento(self.cfg, {"tipo": "staking", "producto": "btc", "unidades": "1"})

    def test_editar_una_recompensa(self):
        m = almacen.guarda_movimiento(self.cfg, {"tipo": "staking", "producto": "btc", "fecha": "2026-01-05",
                                                 "unidades": "0,00000037"})
        almacen.guarda_movimiento(self.cfg, {"id": m["id"], "tipo": "staking", "producto": "btc",
                                             "fecha": "2026-01-05", "unidades": "0,00000037", "importe": "0,02"})
        self.assertEqual(len(self.cfg["movimientos"]), 1)
        self.assertEqual(self.cfg["movimientos"][0]["importe"], 0.02)

    def test_suma_unidades_y_se_pueden_vender_todas(self):
        almacen.guarda_movimiento(self.cfg, {"tipo": "compra", "producto": "btc", "fecha": "2026-01-02",
                                             "unidades": "0,01", "importe": "600"})
        almacen.guarda_movimiento(self.cfg, {"tipo": "staking", "producto": "btc", "fecha": "2026-01-05",
                                             "unidades": "0,00000037"})
        self.assertAlmostEqual(almacen.unidades_a(self.cfg, "btc", "2026-01-05"), 0.01000037, places=12)
        self.assertAlmostEqual(almacen.unidades_a(self.cfg, "btc", "2026-01-04"), 0.01, places=12)
        v = almacen.guarda_movimiento(self.cfg, {"tipo": "venta", "producto": "btc", "fecha": "2026-01-06",
                                                 "unidades": "0,01000037", "importe": "700"})
        self.assertEqual(v["unidades"], 0.01000037)


class Lotes(unittest.TestCase):
    P = btc()

    def test_suma_unidades_sin_tocar_lo_aportado_ni_la_tir(self):
        r = motor.aplicar_movimientos(self.P, [mov("2026-01-02", "btc", "compra", 0.01, 600),
                                              staking("2026-01-05", 0.00000037)])
        self.assertAlmostEqual(sum(e[1] for e in r["eventos"]), 0.01000037, places=12)
        self.assertEqual(sum(e[2] for e in r["eventos"]), 600)       # aportado: solo la compra
        self.assertEqual(r["flujos"], [("2026-01-02", -600)])        # el staking no es dinero que entra o sale
        self.assertEqual((r["realizado"], r["dividendos"]), (0, 0))  # ni un cobro: no cuenta dos veces

    def test_la_valoracion_no_es_aportado(self):
        r = motor.aplicar_movimientos(self.P, [mov("2026-01-02", "btc", "compra", 1, 100),
                                              staking("2026-01-05", 0.1, 12)])
        self.assertEqual(sum(e[2] for e in r["eventos"]), 100)
        self.assertEqual(r["flujos"], [("2026-01-02", -100)])
        self.assertEqual(r["staking"], [["2026-01-05", 0.1, 12]])

    def test_compra_staking_y_venta_parcial_fifo(self):
        r = motor.aplicar_movimientos(self.P, [
            mov("2026-01-02", "btc", "compra", 1, 100),
            staking("2026-01-03", 0.5),            # sin valorar
            staking("2026-01-04", 0.5, 60),        # valorada
            mov("2026-01-10", "btc", "venta", 1.25, 250),
        ])
        # FIFO: sale la compra entera (100 €) y 0,25 de la primera recompensa (que no costó dinero).
        self.assertAlmostEqual(r["costeVendido"], 100)
        self.assertAlmostEqual(r["realizado"], 150)
        self.assertAlmostEqual(sum(e[1] for e in r["eventos"]), 0.75)
        self.assertAlmostEqual(sum(e[2] for e in r["eventos"]), 0)
        v = r["ventasDetalle"][0]
        self.assertAlmostEqual(v["costeFiscal"], 100)
        self.assertEqual([c[3] for c in v["compras"]], [None, False])   # compra y recompensa sin valorar
        self.assertAlmostEqual(v["compras"][1][1], 0.25)
        # Quedan 0,25 sin valorar y 0,5 valoradas en 60 €.
        self.assertAlmostEqual(r["stakingVivas"], 0.75)
        self.assertAlmostEqual(r["stakingVivasValor"], 60)
        self.assertAlmostEqual(r["stakingVivasSinValorar"], 0.25)

    def test_venta_de_recompensas_valoradas_usa_su_valor_como_coste_fiscal(self):
        r = motor.aplicar_movimientos(self.P, [
            mov("2026-01-02", "btc", "compra", 1, 100),
            staking("2026-01-04", 0.5, 60),
            mov("2026-01-10", "btc", "venta", 1.5, 300),
        ])
        v = r["ventasDetalle"][0]
        self.assertAlmostEqual(v["coste"], 100)        # lo que pusiste
        self.assertAlmostEqual(v["costeFiscal"], 160)  # lo que cuenta para Hacienda
        self.assertAlmostEqual(r["realizado"], 200)    # ganancia: 300 − 100 (las recompensas son ganancia)
        self.assertEqual(r["stakingVivas"], 0)

    def test_varias_recompensas_del_mismo_dia_son_lotes_distintos(self):
        r = motor.aplicar_movimientos(self.P, [staking("2026-01-05", 0.00000037, mid="a"),
                                              staking("2026-01-05", 0.00000037, mid="b")])
        self.assertEqual(len(r["staking"]), 2)
        self.assertAlmostEqual(r["stakingVivas"], 0.00000074, places=14)

    def test_compras_ventas_y_dividendos_como_antes(self):
        r = motor.aplicar_movimientos(self.P, [mov("2026-01-02", "btc", "compra", 2, 100),
                                              mov("2026-02-02", "btc", "dividendo", 0, 5),
                                              mov("2026-03-02", "btc", "venta", 1, 80)])
        self.assertAlmostEqual(r["costeVendido"], 50)
        self.assertAlmostEqual(r["realizado"], 35)
        self.assertEqual(r["flujos"], [("2026-01-02", -100), ("2026-02-02", 5), ("2026-03-02", 80)])
        self.assertEqual(r["ventasDetalle"][0]["costeFiscal"], r["ventasDetalle"][0]["coste"])
        self.assertEqual(r["staking"], [])

    def test_traspaso_lleva_la_recompensa_sin_contarla_como_aportado(self):
        P = [btc("a"), btc("b", codigo="BTC2-EUR")]
        movs = motor.expande_traspasos([mov("2026-01-02", "a", "compra", 1, 100), staking("2026-01-03", 1, 50, "a"),
                                        mov("2026-02-01", "a", "traspaso", 2, 300, destino="b", unidadesDestino=2)])
        por = {"a": [m for m in movs if m["producto"] == "a"], "b": [m for m in movs if m["producto"] == "b"]}
        r = motor.aplicar_todos(P, por, conservar_lotes=True)
        self.assertAlmostEqual(sum(e[2] for e in r["b"]["eventos"]), 100)   # llega lo aportado, no los 50 €
        self.assertAlmostEqual(r["b"]["stakingVivas"], 1)
        self.assertAlmostEqual(r["b"]["stakingVivasValor"], 50)


class Patrimonio(ConCarpeta):
    PRECIO = {"BTC-EUR": serie_inventada(base=60000, desde="2025-12-01", paso=0)}

    def construye(self, movs):
        with PreciosInventados(self.PRECIO):
            return motor.construir(cartera([btc()], movs), self.carpeta, descargar=False)

    def test_posicion_valor_y_rentabilidad_con_recompensas(self):
        D = self.construye([mov("2026-01-02", "btc", "compra", 0.01, 500),
                            staking("2026-01-05", 0.00000037), staking("2026-01-06", 0.001, 60)])
        p = D["productos"][0]
        self.assertEqual(p["participaciones"], 0.01100037)
        self.assertEqual(p["titulos"], 0.01100037)
        self.assertEqual(p["aportado"], 500)                             # las recompensas no son aportado
        self.assertEqual(p["precioMedio"], 50000)                        # 500 € entre las 0,01 compradas
        self.assertAlmostEqual(p["valor"], round(0.01100037 * 60000, 2))
        self.assertAlmostEqual(p["plusvalia"], round(0.01100037 * 60000 - 500, 2))
        self.assertEqual(p["realizado"], 0)                              # ni dividendos: no cuenta dos veces
        self.assertEqual(p["aportaciones"][0]["importe"], 500)
        self.assertEqual(len(p["aportaciones"]), 1)                      # no son compras
        s = p["staking"]
        self.assertEqual((s["numero"], s["sinValorar"], s["unidades"]), (2, 1, 0.00100037))
        self.assertEqual(s["valorRecibido"], 60)
        self.assertAlmostEqual(s["valorHoy"], round(0.00100037 * 60000, 2))
        self.assertEqual(D["total"]["aportado"], 500)
        self.assertGreater(p["tir"], 0)    # más valor con el mismo dinero
        self.assertNotIn("_mv", p)

    def test_solo_recompensas(self):
        D = self.construye([staking("2026-01-05", 0.5)])
        p = D["productos"][0]
        self.assertEqual(p["participaciones"], 0.5)
        self.assertEqual(p["valor"], 30000)
        self.assertIsNone(p["aportado"])        # no hay rentabilidad sobre 0 € puestos
        self.assertIsNone(p["precioMedio"])     # ni un precio de compra de 0 €
        self.assertEqual(D["total"]["patrimonio"], 30000)

    def test_sin_cotizacion_vale_lo_anotado_al_recibirla(self):
        cfg = cartera([btc(codigo="RARO-EUR")], [staking("2026-01-05", 2, 3), staking("2026-01-06", 2)])
        with PreciosInventados({"RARO-EUR": {}}):
            D = motor.construir(cfg, self.carpeta, descargar=False)
        p = D["productos"][0]
        self.assertEqual(p["participaciones"], 4)
        self.assertEqual(p["valor"], 6)          # 4 unidades a 1,5 €, el precio al recibir la valorada

    def test_ocultar_importes_escala_lo_del_staking(self):
        D = self.construye([mov("2026-01-02", "btc", "compra", 0.01, 500), staking("2026-01-06", 0.001, 60)])
        s = exportar.sin_importes(D)["productos"][0]["staking"]
        real = D["productos"][0]["staking"]
        self.assertNotEqual(s["valorHoy"], real["valorHoy"])
        self.assertNotEqual(s["valorRecibido"], real["valorRecibido"])
        self.assertEqual(s["numero"], real["numero"])


class Renta(unittest.TestCase):
    def informe(self, movs, ano="2026"):
        return fiscal.informe(cartera([btc()], movs), ano=ano)

    def test_venta_de_recompensas_sin_valorar_avisa_y_no_es_coste_cero_confirmado(self):
        inf = self.informe([mov("2026-01-02", "btc", "compra", 1, 100), staking("2026-01-03", 0.5),
                            mov("2026-02-01", "btc", "venta", 1.5, 300)])
        v = inf["ventas"][0]
        self.assertTrue(v["adquisicionIncompleta"])
        self.assertEqual(v["adquisicion"], 100)
        self.assertTrue(any("staking sin valorar" in a for a in v["avisos"]))
        self.assertFalse(any("cuadrar participaciones" in a for a in v["avisos"]))
        self.assertEqual(inf["staking"][0]["sinValorar"], 1)
        self.assertTrue(any("1 de este año no tienen ese valor anotado" in a for a in inf["avisos"]))
        self.assertIn("Recompensas de staking", fiscal.csv_texto(inf))

    def test_venta_de_recompensas_valoradas(self):
        inf = self.informe([mov("2026-01-02", "btc", "compra", 1, 100), staking("2026-01-03", 0.5, 40),
                            mov("2026-02-01", "btc", "venta", 1.5, 300)])
        v = inf["ventas"][0]
        self.assertEqual((v["adquisicion"], v["ganancia"]), (140, 160))
        self.assertNotIn("adquisicionIncompleta", v)
        self.assertEqual(v["avisos"], [])
        self.assertEqual(inf["totales"]["staking"], 40)
        self.assertEqual([c.get("staking") for c in v["compras"]], [None, True])

    def test_ano_solo_con_recompensas(self):
        inf = self.informe([staking("2025-06-01", 0.1)], ano=None)
        self.assertIn("2025", inf["anos"])
        self.assertEqual(inf["staking"][0]["recompensas"], 1)
        self.assertEqual(inf["ventas"], [])


class Importar(ConCarpeta):
    def setUp(self):
        super().setUp()
        self.cfg = cartera([btc(), {**btc("b2m"), "nombre": "Bit2Me", "corto": "B2M", "codigo": "B2M-EUR",
                                    "identificador": "B2M"}])

    def test_bit2me_sin_importe(self):
        inf = importa(self.cfg, ["2026-01-01;B2M;B2M;cripto;staking;1.23456789;;EUR;;Bit2Me staking",
                                 "2026-01-05;BTC;BTC;cripto;staking;0.00000037;;EUR;;Bit2Me staking"], self.carpeta)
        self.assertEqual(inf["errores"], [])
        self.assertEqual(inf["añadidos"], 2)
        self.assertEqual((inf["totales"]["numStaking"], inf["totales"]["stakingSinValorar"]), (2, 2))
        self.assertEqual(inf["totales"]["compras"], 0)            # no son compras ni dividendos
        self.assertEqual(inf["totales"]["dividendos"], 0)
        self.assertTrue(all("sin valorar" in f["marcas"] for f in inf["filas"]))
        guardados = {m["producto"]: m for m in self.cfg["movimientos"]}
        self.assertEqual(guardados["b2m"]["unidades"], 1.23456789)
        self.assertEqual(guardados["btc"]["unidades"], 0.00000037)
        self.assertNotIn("importe", guardados["btc"])

    def test_con_valoracion_en_otra_moneda(self):
        with mock.patch.object(motor, "serie_cambio", lambda moneda, carpeta, fresca=False: {"2026-01-05": 0.5}):
            inf = importa(self.cfg, ["2026-01-05;BTC;BTC;cripto;staking;0,001;0,04;USD;;"], self.carpeta)
        self.assertEqual(inf["errores"], [])
        self.assertEqual(self.cfg["movimientos"][0]["importe"], 0.02)

    def test_varias_iguales_el_mismo_dia_y_reimportar_no_duplica(self):
        filas = ["2026-01-05;BTC;BTC;cripto;staking;0,00000037;;;;"] * 2 + ["2026-01-05;BTC;BTC;cripto;staking;0,00000031;;;;"]
        self.assertEqual(importa(self.cfg, filas, self.carpeta)["añadidos"], 3)
        otra = importa(self.cfg, filas, self.carpeta)
        self.assertEqual((otra["añadidos"], otra["repetidos"]), (0, 3))
        self.assertEqual(len(self.cfg["movimientos"]), 3)

    def test_extracto_mas_largo_anade_solo_lo_nuevo(self):
        # Con la firma de 4 decimales, 0,00000031 parecía la misma que 0,00000037 y se perdía.
        importa(self.cfg, ["2026-01-05;BTC;BTC;cripto;staking;0,00000037;;;;"], self.carpeta)
        inf = importa(self.cfg, ["2026-01-05;BTC;BTC;cripto;staking;0,00000037;;;;",
                                 "2026-01-05;BTC;BTC;cripto;staking;0,00000037;;;;",
                                 "2026-01-05;BTC;BTC;cripto;staking;0,00000031;;;;"], self.carpeta)
        self.assertEqual((inf["añadidos"], inf["repetidos"]), (2, 1))
        self.assertAlmostEqual(sum(m["unidades"] for m in self.cfg["movimientos"]), 0.00000105, places=14)

    def test_reimportar_ya_valorado_no_duplica(self):
        importa(self.cfg, ["2026-01-05;BTC;BTC;cripto;staking;0,001;;;;"], self.carpeta)
        inf = importa(self.cfg, ["2026-01-05;BTC;BTC;cripto;staking;0,001;60;;;"], self.carpeta)
        self.assertEqual((inf["añadidos"], inf["repetidos"]), (0, 1))

    def test_cientos_de_recompensas_con_sus_cantidades_exactas(self):
        filas, total = [], Decimal(0)
        for i in range(470):
            u = Decimal(f"0.{i + 1:08d}")
            total += u
            filas.append(f"2025-{1 + i % 12:02d}-{1 + i % 28:02d};{'BTC' if i % 2 else 'B2M'};;cripto;staking;{u:f};;EUR;;")
        inf = importa(self.cfg, filas, self.carpeta)
        self.assertEqual((inf["añadidos"], inf["errores"]), (470, []))
        guardado = sum(Decimal(repr(m["unidades"])) for m in self.cfg["movimientos"])
        self.assertEqual(guardado, total)
        self.assertEqual(importa(self.cfg, filas, self.carpeta)["repetidos"], 470)

    def test_unidades_negativas_ausentes_o_demasiado_pequenas(self):
        inf = importa(self.cfg, ["2026-01-05;BTC;BTC;cripto;staking;-0,5;;;;",
                                 "2026-01-05;BTC;BTC;cripto;staking;;;;;",
                                 "2026-01-05;BTC;BTC;cripto;staking;0,000000001;;;;"], self.carpeta)
        self.assertEqual([e["fila"] for e in inf["errores"]], [2, 3, 4])
        self.assertEqual(self.cfg["movimientos"], [])

    def test_notacion_cientifica_de_excel(self):
        # Excel guarda así los números muy pequeños al volver a guardar el CSV.
        importa(self.cfg, ["2026-01-05;BTC;BTC;cripto;staking;3,7E-07;;;;", "2026-01-06;BTC;BTC;cripto;staking;1e-8;;;;"],
                self.carpeta)
        self.assertEqual([m["unidades"] for m in self.cfg["movimientos"]], [0.00000037, 0.00000001])

    def test_mas_de_8_decimales_se_avisa(self):
        inf = importa(self.cfg, ["2026-01-05;BTC;BTC;cripto;staking;0,123456789;;;;"], self.carpeta)
        self.assertEqual(self.cfg["movimientos"][0]["unidades"], 0.12345679)
        self.assertTrue(any("8 decimales" in a for a in inf["avisos"]))

    def test_en_un_producto_que_no_es_cripto_da_error_en_su_fila(self):
        self.cfg["productos"].append({"id": "x", "nombre": "X", "tipo": "etf", "fuente": "yahoo", "codigo": "X.DE",
                                      "identificador": "X"})
        inf = importa(self.cfg, ["2026-01-05;X;X;;staking;1;;;;"], self.carpeta)
        self.assertEqual(inf["añadidos"], 0)
        self.assertIn("criptomoneda", inf["errores"][0]["mensaje"])

    def test_producto_nuevo_elige_la_criptomoneda(self):
        cands = [{"fuente": "yahoo", "codigo": "SOL", "nombre": "Un ETF", "tipo": "etf", "moneda": "USD"},
                 {"fuente": "yahoo", "codigo": "SOL-EUR", "nombre": "Solana", "tipo": "cripto", "moneda": "EUR"}]
        cfg = cartera()
        with mock.patch.object(importar.buscar, "buscar", lambda q: cands):
            inf = importa(cfg, ["2026-01-05;SOL;Solana;cripto;staking;0,5;;;;"], self.carpeta)
        self.assertEqual(inf["errores"], [])
        self.assertEqual((cfg["productos"][0]["tipo"], cfg["productos"][0]["codigo"]), ("cripto", "SOL-EUR"))

    def test_cripto_que_solo_aparece_como_fondo_no_se_crea(self):
        # «EURR» (una moneda estable) también es el nombre de unos fondos: no es esa cripto.
        cands = [{"fuente": "morningstar", "codigo": "F0000X", "nombre": "Un fondo", "tipo": "fondo", "moneda": "EUR"}]
        cfg = cartera()
        with mock.patch.object(importar.buscar, "buscar", lambda q: cands):
            inf = importa(cfg, ["2026-01-05;EURR;EURR;cripto;staking;0,02;;;;"], self.carpeta)
        self.assertEqual((inf["añadidos"], inf["productosNuevos"], cfg["productos"]), (0, [], []))
        self.assertIn("como criptomoneda", inf["errores"][0]["mensaje"])

    def test_cada_fila_de_un_producto_no_encontrado_sale_en_los_errores(self):
        cfg = cartera()
        with mock.patch.object(importar.buscar, "buscar", lambda q: []):
            inf = importa(cfg, ["2026-01-05;SOL2;SOL2;cripto;staking;0,00002281;;;;",
                                "2026-01-12;SOL2;SOL2;cripto;staking;0,00002281;;;;"], self.carpeta)
        self.assertEqual([e["fila"] for e in inf["errores"]], [2, 3])
        self.assertEqual(inf["errores"][0]["mensaje"], inf["errores"][1]["mensaje"])

    def test_staking_etiquetado_como_dividendo(self):
        # Así lo devolvió una IA con un extracto de Bit2Me: «dividendo», sin importe y «Staking» en la nota.
        inf = importa(self.cfg, ["2026-01-05;BTC;BTC;cripto;dividendo;0.00000037;;;0;Staking",
                                 "2026-01-05;B2M;B2M;cripto;dividendo;-1;;;0;Staking"], self.carpeta)
        self.assertEqual(inf["añadidos"], 1)
        self.assertEqual(inf["filas"][0]["tipo"], "staking")
        self.assertIn("era «dividendo»", inf["filas"][0]["marcas"])
        self.assertEqual([(m["tipo"], m["unidades"]) for m in self.cfg["movimientos"]], [("staking", 0.00000037)])
        self.assertIn("en positivo", inf["errores"][0]["mensaje"])     # la negativa sigue rechazada

    def test_un_dividendo_de_verdad_sigue_siendo_dividendo(self):
        inf = importa(self.cfg, ["2026-01-05;BTC;BTC;cripto;dividendo;;1,5;;;"], self.carpeta)
        self.assertEqual(self.cfg["movimientos"][0]["tipo"], "dividendo")
        self.assertEqual(inf["totales"]["dividendos"], 1.5)
        # Sin decir que es una cripto, sin importe no se adivina: error con la pista.
        inf = importa(self.cfg, ["2026-01-06;BTC;BTC;;dividendo;0.00000037;;;;"], self.carpeta)
        self.assertIn("pon «staking» en tipo_movimiento", inf["errores"][0]["mensaje"])
        inf = importa(self.cfg, ["2026-01-05;BTC;BTC;cripto;compra;0.00000037;;;;"], self.carpeta)
        self.assertEqual(inf["errores"][0]["mensaje"], "No tiene importe.")

    def test_compras_sin_importe_siguen_dando_error(self):
        inf = importa(self.cfg, ["2026-01-05;BTC;BTC;cripto;compra;0,5;;;;"], self.carpeta)
        self.assertEqual(inf["errores"][0]["mensaje"], "No tiene importe.")

    def test_exportar_e_importar_sin_perder_nada(self):
        importa(self.cfg, ["2026-01-02;BTC;BTC;cripto;compra;0,01;500;;;",
                           "2026-01-05;BTC;BTC;cripto;staking;0,00000037;;;;Bit2Me",
                           "2026-01-05;BTC;BTC;cripto;staking;0,00000037;;;;Bit2Me",
                           "2026-01-06;B2M;B2M;cripto;staking;1,23456789;0,25;;;"], self.carpeta)
        antes = sorted((m["fecha"], m["producto"], m["tipo"], m["unidades"], m.get("importe"))
                       for m in self.cfg["movimientos"])
        tabla, error = importar.leer_tabla("mis_datos.xlsx", plantilla.mis_datos(self.cfg))
        self.assertIsNone(error)
        # Sobre la misma cartera, nada nuevo...
        inf = importar.aplicar(self.cfg, importar.preparar_tabla(self.cfg, tabla, self.carpeta))
        self.assertEqual((inf["añadidos"], inf["repetidos"]), (0, 4))
        # ...y en una vacía con los mismos productos, lo mismo que había.
        vacia = cartera(self.cfg["productos"])
        importar.aplicar(vacia, importar.preparar_tabla(vacia, tabla, self.carpeta))
        despues = sorted((m["fecha"], m["producto"], m["tipo"], m["unidades"], m.get("importe"))
                         for m in vacia["movimientos"])
        self.assertEqual(despues, antes)

    def test_la_plantilla_lo_explica(self):
        self.assertIn("staking", plantilla.TIPOS_MOVIMIENTO)
        self.assertTrue(any(f[4] == "staking" and f[6] is None for f in plantilla.EJEMPLO))
        with open(importar.__file__.replace("importar.py", "prompt_ia.txt"), encoding="utf-8") as f:
            self.assertIn("staking", f.read())


class Buscar(unittest.TestCase):
    def test_cripto_que_yahoo_solo_tiene_en_dolares_sale_de_coingecko(self):
        # Yahoo conoce B2M-USD pero no B2M-EUR: antes no se miraba CoinGecko y la moneda «no existía».
        yahoo = [{"symbol": "0P0001X.F", "quoteType": "MUTUALFUND", "longname": "Un fondo"},
                 {"symbol": "B2M-USD", "quoteType": "CRYPTOCURRENCY", "shortname": "Bit2Me USD"}]
        monedas = [{"id": "bit2me", "symbol": "b2m", "name": "Bit2Me", "market_cap_rank": 1062}]
        precios = {("coingecko", "bit2me"): {"precio": 0.004, "moneda": "EUR", "fecha": "2026-10-23", "mercado": "CoinGecko"},
                   ("yahoo", "0P0001X.F"): {"precio": 10.0, "moneda": "EUR", "fecha": "2026-10-23"}}
        with mock.patch.object(importar.buscar, "yahoo_buscar", lambda q, n=8: yahoo), \
                mock.patch.object(importar.buscar, "cg_buscar", lambda q: monedas), \
                mock.patch.object(importar.buscar, "probar", lambda f, c: precios.get((f, c))):
            res = importar.buscar.buscar("B2M")
        cripto = [r for r in res if r["tipo"] == "cripto"]
        self.assertEqual([(r["fuente"], r["codigo"], r["identificador"]) for r in cripto], [("coingecko", "bit2me", "B2M")])
        self.assertEqual(cripto[0]["precio"], 0.004)


if __name__ == "__main__":
    unittest.main()
