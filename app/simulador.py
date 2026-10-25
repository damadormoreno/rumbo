# -*- coding: utf-8 -*-
"""
simulador.py  ·  ¿Cuánto pagaría a Hacienda si vendo? (orientativo)
===================================================================
Quieres sacar un importe (o unas participaciones de un producto). Para cada producto que
tienes, Rumbo calcula qué lotes saldrían con el mismo FIFO que el panel y la Renta (lo
primero que compraste es lo primero que vendes, y los traspasos entre fondos conservan el
coste y la fecha), cuánto ganarías o perderías y el IRPF que añadiría esa venta a lo que ya
llevas este año. Así se ve de dónde sacar el dinero pagando menos.

Lo que ya llevas este año sale de fiscal.informe: tus ventas (ganancias y pérdidas) y los
dividendos, intereses y recompensas de staking valoradas que anotaste. Con eso la nueva
ganancia cae en su tramo, y una pérdida compensa lo ya ganado.

Una recompensa de staking que sale en la venta cuesta lo que valía al recibirla; si no lo
anotaste, ese coste falta (no es 0) y se avisa de que la ganancia sale de más.

Solo simula: no guarda nada. No es asesoramiento fiscal: Rumbo no sabe las pérdidas de
años anteriores que tengas pendientes, ni tus retenciones, ni tu situación.
"""

import datetime as dt

from . import almacen, fiscal, motor

# Escala de la base liquidable del ahorro: (hasta cuántos euros, tipo). Es la suma de la
# escala estatal (art. 66.1 de la Ley 35/2006 del IRPF) y la autonómica (art. 76), del
# 9,5 + 9,5 % al 15 + 15 %. Vigente desde el 1 de enero de 2025 (disposición final 7.2 de la
# Ley 7/2024, de 20 de diciembre, BOE-A-2024-26694) y comprobada para 2026 en el texto
# consolidado del BOE: https://www.boe.es/buscar/act.php?id=BOE-A-2006-20764#a66
# Si cambia, basta con tocar esta tabla.
TRAMOS_AHORRO = (
    (6000, 0.19),
    (50000, 0.21),
    (200000, 0.23),
    (300000, 0.27),
    (None, 0.30),
)
# Pérdidas de ventas contra dividendos e intereses (y al revés): hasta el 25 % (art. 49 LIRPF).
COMPENSACION_CRUZADA = 0.25
# Por debajo de esta parte de ganancia sobre lo vendido, se dice que tiene «poca plusvalía».
POCA_PLUSVALIA = 0.10
# Cuentas, deudas, planes de pensiones (un rescate es rendimiento del trabajo), pisos (su venta
# tiene sus propias reglas) y préstamos P2P (se devuelven, no se venden): no entran.
FUERA = ("efectivo", "deuda", "pension", "inmueble", "p2p")
MAXIMO = 1e12   # más que esto no es una cantidad, es una errata

AVISO = ("Estimación orientativa, no asesoramiento fiscal. Ventas como Hacienda (FIFO; los traspasos entre fondos "
         "conservan coste y fecha) al valor de hoy y sin comisiones. Cuenta lo que ya vendiste y cobraste este año, pero "
         "no las pérdidas de años anteriores que tengas pendientes ni tu situación: compruébalo antes de vender.")


def r2(x):
    return round(x + 0.0, 2)


def eur(x):
    t = f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return t[:-3] + " €" if t.endswith(",00") else t + " €"


def pct(x):
    return f"{x * 100:.1f}".replace(".", ",") + " %"


def cuota_ahorro(base):
    """IRPF de una base del ahorro con la escala de TRAMOS_AHORRO."""
    cuota, desde = 0.0, 0.0
    for hasta, tipo in TRAMOS_AHORRO:
        if base <= desde:
            break
        tramo = base - desde if hasta is None else min(base, hasta) - desde
        cuota += tramo * tipo
        if hasta is None:
            break
        desde = hasta
    return r2(cuota)


def tipo_marginal(base):
    """Tipo del tramo en el que cae el último euro de la base."""
    for hasta, tipo in TRAMOS_AHORRO:
        if hasta is None or base <= hasta:
            return tipo


def base_ahorro(ganancias, rendimientos):
    """Base del ahorro con el saldo de ventas y el de dividendos e intereses del año: un saldo
    negativo compensa el otro hasta el 25 % de este (lo que sobra pasa a los años siguientes)."""
    if ganancias < 0 < rendimientos:
        c = min(-ganancias, rendimientos * COMPENSACION_CRUZADA)
        ganancias, rendimientos = ganancias + c, rendimientos - c
    elif rendimientos < 0 < ganancias:
        c = min(-rendimientos, ganancias * COMPENSACION_CRUZADA)
        ganancias, rendimientos = ganancias - c, rendimientos + c
    return max(ganancias, 0) + max(rendimientos, 0)


def _vende(lotes, unidades=None, fraccion=None):
    """Los trozos de lote que saldrían, sin tocar 'lotes' (el mismo FIFO del motor)."""
    copia = [list(l) for l in lotes]
    if unidades is not None:
        return motor._saca_fifo(copia, unidades)[0]
    return motor._saca_proporcion(copia, fraccion)


def simular(cfg, valores, producto=None, euros=None, unidades=None, hoy=None, cache=None):
    """
    valores: {producto: lo que vale hoy tu posición, en euros}. Se vende 'euros' de cada producto
    que tienes (o 'unidades' de 'producto', y de los demás lo que valgan esas unidades).
    Devuelve las opciones de menos a más IRPF, cuál es la mejor y por qué. Si lo que pides de
    'producto' es más de lo que tienes, ErrorValidacion. 'cache': la carpeta de precios de Yahoo,
    de la que salen los splits (las participaciones son siempre las de después del split).
    """
    hoy = hoy or dt.date.today()
    errores = []
    productos = {p["id"]: p for p in cfg.get("productos", [])}
    elegido = productos.get(producto) if producto else None
    if producto and not elegido:
        raise almacen.ErrorValidacion(["Ese producto ya no existe."])
    if unidades not in (None, ""):
        if not elegido:
            errores.append("Elige de qué producto son las participaciones.")
        unidades = almacen.numero(unidades, "cuántas participaciones quieres vender", errores, mayor_que=0)
        euros = None
    else:
        unidades = None
        euros = almacen.numero(euros, "cuántos euros quieres sacar", errores, mayor_que=0)
    if any(x is not None and not x < MAXIMO for x in (euros, unidades)):
        errores.append("Esa cantidad es demasiado grande: revísala.")
    if errores:
        raise almacen.ErrorValidacion(errores)

    def nombre(pid):
        p = productos.get(pid) or {}
        return motor.sin_html(p.get("nombre") or p.get("corto") or pid)

    est, _, _ = motor.fifo_cartera(cfg, cache=cache, conservar_lotes=True)
    candidatos, avisos = {}, []
    for pid, p in productos.items():
        valor = float(valores.get(pid) or 0)
        if p.get("tipo") in FUERA or pid not in est or valor <= 0:
            continue
        lotes = [l for l in est[pid]["lotes"] if l[0] > 1e-9 or l[1] > 1e-9]
        if not lotes:
            avisos.append(f"«{nombre(pid)}» no tiene compras anotadas: no sé lo que te costó, así que lo dejo fuera.")
            continue
        candidatos[pid] = (lotes, valor, sum(l[0] for l in lotes))
    if any(p.get("tipo") == "pension" and (valores.get(p["id"]) or 0) > 0 for p in productos.values()):
        avisos.append("Los planes de pensiones no están: lo que rescatas tributa como rendimiento del trabajo (todo, no "
                      "solo lo ganado), no como una venta.")

    if elegido and producto not in candidatos:
        raise almacen.ErrorValidacion([f"Hoy no tienes nada de «{nombre(producto)}» que se pueda vender."])
    if elegido:
        lotes, valor, tenias = candidatos[producto]
        if unidades is not None:
            if tenias <= 1e-9:
                raise almacen.ErrorValidacion([f"«{nombre(producto)}» no tiene participaciones: indica cuántos euros "
                                               "quieres sacar."])
            if unidades > tenias and unidades - tenias <= tenias * 1e-6 + 1e-12:
                unidades = tenias   # todo: los últimos decimales no se pueden escribir exactos
            if unidades > tenias + 1e-9:
                raise almacen.ErrorValidacion([f"De «{nombre(producto)}» solo tienes {almacen.fmt_unidades(tenias)} "
                                               f"participaciones y quieres vender {almacen.fmt_unidades(unidades)}."])
            euros = unidades * valor / tenias
        elif euros > valor + 0.005:
            raise almacen.ErrorValidacion([f"De «{nombre(producto)}» solo tienes {eur(valor)} (lo que vale hoy): no "
                                           f"puedes sacar {eur(euros)}."])

    previo = fiscal.informe(cfg, str(hoy.year), hoy, cache=cache)["totales"]
    gan_previas = previo["saldo"]
    rend_previos = r2(previo["dividendos"] + previo["intereses"] + previo["staking"])
    if previo["stakingSinValorar"]:
        avisos.append(f"{previo['stakingSinValorar']} recompensas de staking de este año no tienen anotado lo que valían: "
                      "no se cuentan en lo que ya llevas (son rendimiento del capital mobiliario).")
    cuota_previa = cuota_ahorro(base_ahorro(gan_previas, rend_previos))

    opciones = []
    for pid, (lotes, valor, tenias) in candidatos.items():
        p = productos[pid]
        o = {"producto": pid, "nombre": nombre(pid), "tipo": motor.TIPOS.get(p.get("tipo"), "Otro"),
             "valor": r2(valor), "alcanza": euros <= valor + 0.005, "unidades": None, "lotes": [], "avisos": []}
        opciones.append(o)
        if not o["alcanza"]:
            o["avisos"].append(f"Solo tienes {eur(valor)}: no llega.")
            continue
        if tenias > 1e-9:
            precio = valor / tenias
            vender = unidades if pid == producto and unidades is not None else min(euros / precio, tenias)
            trozos = _vende(lotes, unidades=vender)
            o["unidades"] = vender
            partes = [(t[0], t[1], t[3], t[0] * precio, motor.de_staking(t[2])) for t in trozos]
        else:
            # Sin participaciones (un producto anotado a mano): sale la misma parte de cada compra.
            trozos = _vende(lotes, fraccion=min(1.0, euros / valor))
            coste_total = sum(t[1] for t in trozos)
            partes = [(None, t[1], t[3], euros * (t[1] / coste_total if coste_total else 1 / len(trozos)),
                       motor.de_staking(t[2])) for t in trozos]
        coste = sum(x[1] for x in partes)
        # staking: None si es una compra; True o False si es una recompensa valorada o sin valorar.
        o["lotes"] = [{"fecha": f, "unidades": u, "coste": r2(c), "valor": r2(v), "ganancia": r2(v - c), "staking": st}
                      for u, c, f, v, st in partes]
        o["coste"], o["ganancia"] = r2(coste), r2(euros - coste)
        o["costeIncompleto"] = any(st is False for *_, st in partes)
        # Con una compra reciente del mismo producto, la pérdida aún no se puede compensar (art. 33.5 LIRPF).
        o["perdidaDiferida"] = o["ganancia"] < 0 and bool(_compra_reciente(cfg, p, hoy))
        base = base_ahorro(gan_previas + (0 if o["perdidaDiferida"] else o["ganancia"]), rend_previos)
        o["impuesto"] = r2(cuota_ahorro(base) - cuota_previa)
        o["tipoMarginal"] = tipo_marginal(base) if o["impuesto"] > 0 else None
        o["avisos"] += _avisos(cfg, p, o, hoy)
    # A igual IRPF, mejor una pérdida que compensa (o se arrastra) que una diferida, y luego la menor ganancia.
    opciones.sort(key=lambda o: (not o["alcanza"], o.get("impuesto", 0), o.get("perdidaDiferida", False),
                                 o.get("ganancia", 0), o["nombre"]))

    validas = [o for o in opciones if o["alcanza"]]
    mejor = validas[0] if validas else None
    elegida = next((o for o in opciones if o["producto"] == producto), None)
    ahorro = r2(elegida["impuesto"] - mejor["impuesto"]) if mejor and elegida and elegida["alcanza"] else None
    return {"euros": r2(euros), "unidades": unidades, "producto": producto, "ano": str(hoy.year),
            "previo": {"ganancias": gan_previas, "rendimientos": rend_previos, "cuota": cuota_previa},
            "opciones": opciones, "mejor": mejor["producto"] if mejor else None, "ahorro": ahorro,
            "porque": _porque(mejor, elegida, euros, ahorro) if mejor else
            f"Ninguno de tus productos llega a {eur(euros)}.",
            "aviso": AVISO, "avisos": avisos}


def _compra_reciente(cfg, p, hoy):
    """«dos meses» o «un año» si compraste este producto dentro de ese plazo (regla de recompra); si no, None."""
    meses = fiscal.VENTANA_RECOMPRA.get(p.get("tipo"))
    if not meses:
        return None
    desde, hasta = fiscal.suma_meses(hoy.isoformat(), -meses), hoy.isoformat()
    if any(m.get("tipo") == "compra" and m.get("producto") == p["id"] and desde <= m.get("fecha", "") <= hasta
           for m in cfg.get("movimientos", [])):
        return "dos meses" if meses == 2 else "un año"


def _avisos(cfg, p, o, hoy):
    avisos = []
    if p.get("tipo") == "fondo":
        avisos.append("Si lo que quieres es cambiar de fondo, no hace falta vender: un traspaso entre fondos de inversión "
                      "no tributa (el nuevo conserva el coste y la fecha de compra).")
    meses = fiscal.VENTANA_RECOMPRA.get(p.get("tipo"))
    if meses and o["ganancia"] < 0:
        plazo = "dos meses" if meses == 2 else "un año"
        if o["perdidaDiferida"]:
            avisos.append(f"Compraste este producto en el último {plazo.replace('dos meses', 'par de meses')}: esa pérdida "
                          f"no podrías compensarla todavía (regla de los {plazo.replace('un año', 'doce meses')}), así "
                          "que no la cuento.")
        else:
            avisos.append(f"Si vuelves a comprarlo en los {plazo.replace('un año', 'doce meses')} siguientes, esa pérdida "
                          "no podrás compensarla todavía.")
    if o["costeIncompleto"]:
        avisos.append("Parte de lo que venderías son recompensas de staking sin valorar: su coste es lo que valían el día "
                      "que las recibiste, y no está anotado. La ganancia y el IRPF que ves salen de más: anótalo en "
                      "Movimientos.")
    if any(l["coste"] <= 0 and l["staking"] is None for l in o["lotes"]):
        avisos.append("Parte de lo que venderías no tiene coste anotado (viene de cuadrar participaciones o de un "
                      "traspaso sin coste): su ganancia saldría más alta de lo que es.")
    return avisos


def _porque(mejor, elegida, euros, ahorro):
    n, g = mejor["nombre"], mejor["ganancia"]
    if g < 0 and mejor["perdidaDiferida"]:
        txt = (f"«{n}» está en pérdidas: sacar {eur(euros)} de ahí da una pérdida de {eur(-g)}, así que no pagas nada. "
               "Pero como lo compraste hace poco, esa pérdida no podrás compensarla todavía.")
    elif g < 0:
        txt = (f"«{n}» tiene lotes en pérdidas: sacar {eur(euros)} de ahí da una pérdida de {eur(-g)}, "
               + (f"que compensa lo que ya has ganado este año y te ahorra {eur(-mejor['impuesto'])}."
                  if mejor["impuesto"] < 0 else
                  "así que no pagas nada (y esa pérdida compensa ganancias de este año o de los cuatro siguientes)."))
    elif g / euros <= POCA_PLUSVALIA:
        txt = (f"«{n}» tiene poca plusvalía: solo el {pct(g / euros)} de lo que vendes es ganancia (lo que saldría "
               "costó casi lo que vale hoy, como suele pasar con un monetario).")
    else:
        txt = f"«{n}» es el que menos ganancia tiene por euro vendido: el {pct(g / euros)} de lo que sacas."
    if elegida and elegida is not mejor:
        if elegida["alcanza"] and ahorro > 0:
            txt += (f" Sacar lo mismo de «{elegida['nombre']}» " +
                    (f"supondría {eur(elegida['impuesto'])} de IRPF: {eur(ahorro)} más." if elegida["impuesto"] >= 0
                     else f"te ahorraría {eur(-elegida['impuesto'])}: {eur(ahorro)} menos."))
        elif elegida["alcanza"]:
            txt += f" Sacarlo de «{elegida['nombre']}» te costaría lo mismo."
    elif elegida:
        txt += " Es el que habías elegido."
    return txt
