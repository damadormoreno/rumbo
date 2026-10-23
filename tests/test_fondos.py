"""Varios fondos de emergencia (o de lo que sea: la casa, la familia…), cada uno con sus productos."""
import unittest

from comun import ConCarpeta, PreciosInventados, cartera, etf, manual
from app import almacen, exportar, motor


def cuenta(pid, **extra):
    return manual(pid, tipo="efectivo", **extra)


class Guardar(unittest.TestCase):
    def setUp(self):
        self.cfg = cartera([cuenta("familia"), manual("monetario", tipo="fondo"), manual("rf", tipo="fondo"),
                            manual("hipoteca", tipo="deuda")])

    def test_una_cartera_de_antes_es_un_fondo_sin_productos(self):
        self.cfg["colchon"] = {"modo": "meses", "meses": 6, "gastoMensual": 2000}
        self.assertEqual(motor.colchones(self.cfg), [
            {"id": "c1", "nombre": "Fondo de emergencia", "modo": "meses", "meses": 6.0, "gastoMensual": 2000.0,
             "importe": 12000.0, "productos": []}])
        self.assertEqual(motor.colchon(self.cfg)["importe"], 12000)

    def test_varios_fondos_con_sus_productos(self):
        almacen.guarda_colchon(self.cfg, {"nuevo": True, "nombre": "Personal", "modo": "importe", "importe": "6.000",
                                          "productos": ["monetario"]})
        almacen.guarda_colchon(self.cfg, {"nuevo": True, "nombre": "Casa", "modo": "importe", "importe": "20000",
                                          "productos": ["rf"]})
        almacen.guarda_colchon(self.cfg, {"nuevo": True, "nombre": "Familia", "modo": "meses", "meses": "3",
                                          "gastoMensual": "1.500", "productos": ["familia"]})
        fondos = motor.colchones(self.cfg)
        self.assertEqual([(c["id"], c["nombre"], c["importe"], c["productos"]) for c in fondos],
                         [("c1", "Personal", 6000, ["monetario"]), ("c2", "Casa", 20000, ["rf"]),
                          ("c3", "Familia", 4500, ["familia"])])
        self.assertNotIn("colchon", self.cfg)
        self.assertEqual(motor.colchon(self.cfg)["importe"], 6000)   # el primero, como antes

    def test_editar_y_borrar_uno(self):
        a = almacen.guarda_colchon(self.cfg, {"nuevo": True, "nombre": "A", "modo": "importe", "importe": "1000"})
        b = almacen.guarda_colchon(self.cfg, {"nuevo": True, "nombre": "B", "modo": "importe", "importe": "2000"})
        almacen.guarda_colchon(self.cfg, {"id": b["id"], "nombre": "B2", "modo": "importe", "importe": "2500",
                                          "productos": ["rf"]})
        self.assertEqual([(c["nombre"], c["importe"]) for c in motor.colchones(self.cfg)], [("A", 1000), ("B2", 2500)])
        almacen.guarda_colchon(self.cfg, {"id": a["id"], "borrar": True})
        self.assertEqual([c["nombre"] for c in motor.colchones(self.cfg)], ["B2"])
        almacen.guarda_colchon(self.cfg, {"borrar": True})     # sin id, como antes: todos
        self.assertEqual(motor.colchones(self.cfg), [])
        self.assertIsNone(motor.colchon(self.cfg))

    def test_sin_id_cambia_el_primero_como_antes(self):
        self.cfg["colchon"] = {"modo": "meses", "meses": 6, "gastoMensual": 2000}
        almacen.guarda_colchon(self.cfg, {"modo": "importe", "importe": "10.000"})
        self.assertEqual([(c["nombre"], c["importe"]) for c in motor.colchones(self.cfg)],
                         [("Fondo de emergencia", 10000)])

    def test_un_producto_solo_en_un_fondo(self):
        almacen.guarda_colchon(self.cfg, {"nuevo": True, "nombre": "Casa", "modo": "importe", "importe": "1",
                                          "productos": ["rf"]})
        with self.assertRaises(almacen.ErrorValidacion) as e:
            almacen.guarda_colchon(self.cfg, {"nuevo": True, "nombre": "Otro", "modo": "importe", "importe": "1",
                                              "productos": ["rf"]})
        self.assertIn("ya está en «Casa»", " ".join(e.exception.errores))

    def test_productos_que_no_valen(self):
        for productos in (["no_existe"], ["hipoteca"]):
            with self.subTest(productos=productos), self.assertRaises(almacen.ErrorValidacion):
                almacen.guarda_colchon(self.cfg, {"nuevo": True, "nombre": "X", "modo": "importe", "importe": "1",
                                                  "productos": productos})

    def test_borrar_un_producto_lo_quita_de_su_fondo(self):
        almacen.guarda_colchon(self.cfg, {"nuevo": True, "nombre": "Casa", "modo": "importe", "importe": "1",
                                          "productos": ["rf", "monetario"]})
        almacen.borra_producto(self.cfg, "rf")
        self.assertEqual(motor.colchones(self.cfg)[0]["productos"], ["monetario"])

    def test_nombre_sin_html_y_por_defecto(self):
        c = almacen.guarda_colchon(self.cfg, {"nuevo": True, "nombre": "<b>Casa</b>", "modo": "importe", "importe": "1"})
        self.assertEqual(c["nombre"], "bCasa/b")
        c = almacen.guarda_colchon(self.cfg, {"nuevo": True, "nombre": " ", "modo": "importe", "importe": "1"})
        self.assertEqual(c["nombre"], "Fondo de emergencia")


class Panel(ConCarpeta):
    def test_los_datos_llevan_los_fondos_y_ocultar_importes_los_escala(self):
        cfg = cartera([etf(), cuenta("familia")],
                      valoraciones=[{"id": "v1", "fecha": "2026-01-02", "producto": "familia", "valor": 5000}])
        almacen.guarda_colchon(cfg, {"nuevo": True, "nombre": "Familia", "modo": "meses", "meses": "3",
                                     "gastoMensual": "1500", "productos": ["familia"]})
        with PreciosInventados():
            D = motor.construir(cfg, self.carpeta, descargar=False)
        self.assertEqual(D["colchones"][0]["nombre"], "Familia")
        self.assertEqual(D["colchon"]["importe"], 4500)
        fuera = exportar.sin_importes(D)["colchones"][0]
        self.assertNotEqual(fuera["importe"], 4500)
        self.assertEqual((fuera["meses"], fuera["productos"]), (3, ["familia"]))


if __name__ == "__main__":
    unittest.main()
