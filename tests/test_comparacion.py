"""«¿Y si lo hubieras metido todo en un indexado?»: la comparación de toda la cartera y la
de solo los productos de largo plazo (sin el colchón ni los monetarios)."""
import unittest

from comun import ConCarpeta, PreciosInventados, cartera, mov, serie_inventada
from app import motor


def fondo(pid, codigo, largo=True):
    return {"id": pid, "nombre": pid.upper(), "corto": pid.upper(), "tipo": "fondo", "fuente": "morningstar",
            "codigo": codigo, "moneda": "EUR", "slot": 1, "largoPlazo": largo}


def traspaso(fecha, origen, destino, unidades, importe, unidades_destino, mid="t1"):
    return {"id": mid, "fecha": fecha, "producto": origen, "destino": destino, "tipo": "traspaso",
            "unidades": unidades, "unidadesDestino": unidades_destino, "importe": importe}


# Precios fijos: el indexado A vale 10 hasta 2023 y 20 desde 2024; B vale 50 y el monetario M, 50.
PRECIOS = {"MS:A": serie_inventada(10, "2020-01-01", "2023-12-31", paso=0) | serie_inventada(20, "2024-01-01", paso=0),
           "MS:B": serie_inventada(50, "2020-01-01", paso=0),
           "MS:M": serie_inventada(50, "2020-01-01", paso=0)}

A, B = fondo("a", "A"), fondo("b", "B")
M = fondo("m", "M", largo=False)
COMPRA_A = mov("2020-01-02", "a", "compra", 100, 1000)
COMPRA_M = mov("2021-01-04", "m", "compra", 20, 1000)


class Comparacion(ConCarpeta):
    def construye(self, cfg):
        with PreciosInventados(PRECIOS):
            return motor.construir(cfg, self.carpeta, descargar=False)

    def mismas_cifras(self, c1, c2):
        """Dos comparaciones con el mismo valor, aportado, TIR y referencias."""
        self.assertAlmostEqual(c1["tuValor"], c2["tuValor"], places=2)
        self.assertAlmostEqual(c1["aportado"][-1], c2["aportado"][-1], places=2)
        self.assertAlmostEqual(c1["tuTir"], c2["tuTir"], places=4)
        self.assertEqual(c1["desde"], c2["desde"])
        self.assertEqual([r["id"] for r in c1["referencias"]], [r["id"] for r in c2["referencias"]])
        for r1, r2 in zip(c1["referencias"], c2["referencias"]):
            self.assertAlmostEqual(r1["valor"], r2["valor"], places=2, msg=r1["id"])
            self.assertAlmostEqual(r1["tir"], r2["tir"], places=4, msg=r1["id"])

    def test_solo_largo_plazo_deja_fuera_lo_que_no_lo_es(self):
        D = self.construye(cartera([A, M], [COMPRA_A, COMPRA_M]))
        C = D["comparacion"]
        self.assertAlmostEqual(C["tuValor"], 2000 + 1000)          # toda la cartera, como siempre
        self.assertAlmostEqual(C["aportado"][-1], 2000)
        L = C["soloLargoPlazo"]
        self.assertAlmostEqual(L["tuValor"], 2000)                 # solo el indexado
        self.assertAlmostEqual(L["aportado"][-1], 1000)
        self.assertEqual(L["excluidos"], ["M"])
        self.assertNotIn("soloLargoPlazo", L)
        # Lo mismo que si el monetario no existiera.
        self.mismas_cifras(L, self.construye(cartera([A], [COMPRA_A]))["comparacion"])
        self.assertNotAlmostEqual(L["tuTir"], C["tuTir"], places=3)

    def test_traspaso_de_un_monetario_a_un_indexado_es_dinero_que_entra(self):
        D = self.construye(cartera([A, M], [mov("2020-01-02", "m", "compra", 20, 1000),
                                            traspaso("2022-03-01", "m", "a", 20, 1000, 100)]))
        L = D["comparacion"]["soloLargoPlazo"]
        self.assertEqual(L["desde"], "2022-03-01")
        self.assertAlmostEqual(L["aportado"][-1], 1000)
        # Como si ese día hubieras comprado el indexado con dinero de fuera.
        self.mismas_cifras(L, self.construye(cartera([A], [mov("2022-03-01", "a", "compra", 100, 1000)]))["comparacion"])
        # Para toda la cartera sigue sin ser dinero nuevo.
        self.assertAlmostEqual(D["comparacion"]["aportado"][-1], 1000)
        self.assertEqual(D["comparacion"]["desde"], "2020-01-02")

    def test_traspaso_entre_dos_de_largo_plazo_no_es_flujo(self):
        D = self.construye(cartera([A, B, M], [COMPRA_A, COMPRA_M,
                                               traspaso("2024-03-01", "a", "b", 100, 2000, 40)]))
        L = D["comparacion"]["soloLargoPlazo"]
        self.assertEqual({v for v in L["aportado"] if v is not None}, {1000})
        self.mismas_cifras(L, self.construye(cartera([A], [COMPRA_A]))["comparacion"])

    def test_sin_productos_de_largo_plazo_no_hay_opcion(self):
        D = self.construye(cartera([M], [COMPRA_M]))
        self.assertIsNotNone(D["comparacion"])
        self.assertIsNone(D["comparacion"]["soloLargoPlazo"])

    def test_todo_de_largo_plazo_no_hay_opcion(self):
        D = self.construye(cartera([A, B], [COMPRA_A, mov("2021-01-04", "b", "compra", 20, 1000)]))
        self.assertIsNone(D["comparacion"]["soloLargoPlazo"])

    def test_toda_la_cartera_no_depende_de_la_marca(self):
        con = self.construye(cartera([A, M], [COMPRA_A, COMPRA_M]))["comparacion"]
        sin = self.construye(cartera([A, dict(M, largoPlazo=True)], [COMPRA_A, COMPRA_M]))["comparacion"]
        self.mismas_cifras(con, sin)
        self.assertEqual(con["tuya"], sin["tuya"])


if __name__ == "__main__":
    unittest.main()
