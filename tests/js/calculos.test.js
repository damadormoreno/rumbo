// Pruebas de las cuentas que hace el panel en el navegador (app/web/calculos.js).
// Se lanzan solas con el resto (tests/test_calculos_js.py) o a mano:  node tests/js/calculos.test.js
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const C = require(path.join(__dirname, "..", "..", "app", "web", "calculos.js"));

const cerca = (a, b, tol = 0.01) => assert.ok(Math.abs(a - b) <= tol, `${a} no está cerca de ${b}`);

test("leeImporte entiende cómo escribe la gente", () => {
  assert.equal(C.leeImporte("1.900"), 1900);        // mil novecientos
  assert.equal(C.leeImporte("1900,5"), 1900.5);
  assert.equal(C.leeImporte("1.900,50 €"), 1900.5);
  assert.equal(C.leeImporte("1900.5"), 1900.5);     // antes daba 19.005
  assert.equal(C.leeImporte("12.345.678"), 12345678);
  assert.ok(Number.isNaN(C.leeImporte("")));
  assert.ok(Number.isNaN(C.leeImporte("mil")));
});

test("TIR: un 10 % en un año y las pérdidas", () => {
  const t0 = Date.parse("2023-01-01"), t1 = Date.parse("2024-01-01");
  cerca(C.xirr([{ t: t0, v: -100 }, { t: t1, v: 110 }]), 0.10, 0.002);
  cerca(C.xirr([{ t: t0, v: -100 }, { t: t1, v: 80 }]), -0.20, 0.002);
  assert.equal(C.xirr([{ t: t0, v: -100 }]), null);
  assert.equal(C.xirr([{ t: t0, v: 100 }, { t: t1, v: 50 }]), null);   // sin dinero puesto no hay TIR
});

const D = {
  fechas: ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"],
  fechaExtracto: "2024-01-04",
  aportacionesMensuales: { meses: ["2023-11", "2023-12", "2024-01"], porProducto: { a: [100, 0, 200], b: [0, 50, 50] } },
};
const A = { id: "a", valor: 1100, aportado: 1000, realizado: 20, serie: [1000, 1200, 900, 1100], serieAportado: [1000, 1000, 1000, 1000],
  aportaciones: [{ importe: 1000 }], flujos: [["2023-01-04", -1000]] };
const B = { id: "b", valor: 500, aportado: null, serie: [null, 500, 500, 500], serieAportado: [] };

test("métricas: valor, plusvalía, ritmo, racha y peor caída", () => {
  const m = C.metricas([A, B], D);
  assert.equal(m.valor, 1600);
  assert.equal(m.aportado, 1000);
  assert.equal(m.plusvalia, 100);                    // solo de lo que tiene coste
  cerca(m.rentabilidad, 0.1);
  assert.equal(m.realizado, 20);
  assert.equal(m.numAportaciones, 1);
  cerca(m.ritmo, (100 + 50 + 250) / 3);
  assert.equal(m.racha, 3);                          // noviembre, diciembre y enero seguidos
  assert.deepEqual(m.serie, [1000, 1700, 1400, 1600]);
  cerca(m.caida, 1400 / 1700 - 1, 1e-9);
  assert.equal(m.caidaFecha, "2024-01-03");
  cerca(m.tir, 0.10, 0.003);                         // 1.000 → 1.100 en un año
});

test("métricas con el valor en vivo y con la cartera filtrada", () => {
  const vivo = p => (p.id === "a" ? 1210 : p.valor);
  assert.equal(C.metricas([A, B], D, vivo).plusvalia, 210);
  const soloB = C.metricas([B], D);
  assert.equal(soloB.aportado, 0);
  assert.equal(soloB.plusvalia, null);
  assert.equal(soloB.racha, 2);                      // las aportaciones de b: diciembre y enero
});

test("países y sectores: cada producto pesa lo que vale, y solo su parte en bolsa", () => {
  const prods = [
    { valor: 6000, exposicion: { rv: 1, paises: [["Estados Unidos", 70], ["Japón", 30]], sectores: [["Tecnología", 100]] } },
    { valor: 4000, exposicion: { rv: 0.5, paises: [["Japón", 100]], sectores: [["Salud", 100]] } },   // mixto
    { valor: 1000, tipoClave: "efectivo" },                                                           // cuenta
    { valor: 500, tipoClave: "pension", corto: "Plan" },                                              // sin datos
    { valor: 0, exposicion: { paises: [["China", 100]], sectores: [] } },                              // vendido
  ];
  const r = C.agregaExposicion(prods);
  assert.equal(r.enBolsa, 8000);
  assert.equal(r.fuera, 3000);                       // 2.000 de renta fija del mixto + la cuenta
  assert.equal(r.sinDatos, 500);
  assert.deepEqual(r.sinNombre, ["Plan"]);
  assert.deepEqual(r.paises, [["Estados Unidos", 52.5], ["Japón", 47.5]]);
  assert.deepEqual(r.sectores, [["Tecnología", 75], ["Salud", 25]]);
});

test("países: los 9 mayores y el resto en «Otros» (también el «Resto» de las fichas)", () => {
  // 12 países que suman 100 % (como las fichas de Morningstar) y un «Resto» vacío.
  const paises = Array.from({ length: 12 }, (_, i) => ["P" + i, (12 - i) * 100 / 78]).concat([["Resto", 0]]);
  const r = C.agregaExposicion([{ valor: 1000, exposicion: { paises, sectores: [] } }]);
  assert.equal(r.paises.length, 10);
  assert.equal(r.paises[9][0], "Otros");
  cerca(r.paises.reduce((a, x) => a + x[1], 0), 100, 0.3);
  assert.deepEqual(C.agregaExposicion([{ valor: 100, tipoClave: "cripto" }]).paises, []);
});

test("liquidez: cuentas y monetarios, o lo que marques", () => {
  assert.ok(C.esLiquidez({ tipoClave: "efectivo" }));
  assert.ok(C.esLiquidez({ tipoClave: "fondo", clase: "Mercado Monetario Corto Plazo EUR" }));
  assert.ok(!C.esLiquidez({ tipoClave: "fondo", clase: "RV Global" }));
  assert.ok(!C.esLiquidez({ tipoClave: "efectivo", liquidez: false }));   // lo que dice el usuario manda
  assert.ok(C.esLiquidez({ tipoClave: "fondo", liquidez: true }));
  const prods = [{ tipoClave: "efectivo", valor: 2500 }, { tipoClave: "fondo", clase: "Monetario", valor: 7400 },
    { tipoClave: "fondo", valor: 30000 }, { tipoClave: "efectivo", valor: 0 }];
  const r = C.resumenLiquidez(prods, { modo: "meses", meses: 6, gastoMensual: 1500, importe: 9000 });
  assert.equal(r.liquidez, 9900);
  assert.equal(r.productos.length, 2);
  assert.equal(r.productos[0].valor, 7400);           // de mayor a menor
  assert.equal(r.sobra, 900);
  cerca(r.meses, 6.6);
  assert.equal(r.pct, 1);
  const corto = C.resumenLiquidez(prods, { modo: "importe", importe: 20000 });
  assert.equal(corto.sobra, -10100);                  // le falta para completarlo
  assert.equal(corto.meses, null);
  cerca(corto.pct, 0.495);
  assert.equal(C.resumenLiquidez(prods, null).objetivo, null);
});

test("varios fondos: los suyos, o la liquidez que no está en ninguno", () => {
  const prods = [
    { id: "mon1", tipoClave: "fondo", clase: "Monetario", valor: 5000 },      // fondo personal
    { id: "mon2", tipoClave: "fondo", clase: "Monetario", valor: 9000 },      // casa
    { id: "rfuc", tipoClave: "fondo", clase: "RF Ultra Corto Plazo", valor: 12000 },   // casa, aunque no es liquidez
    { id: "cta", tipoClave: "efectivo", valor: 3000 },                        // familia
    { id: "libre", tipoClave: "efectivo", valor: 4000 },                      // en ningún fondo
    { id: "etf", tipoClave: "etf", valor: 50000 },
  ];
  const fondos = [
    { id: "c1", nombre: "Personal", modo: "importe", importe: 6000, productos: ["mon1"] },
    { id: "c2", nombre: "Casa", modo: "importe", importe: 20000, productos: ["mon2", "rfuc"] },
    { id: "c3", nombre: "Familia", modo: "meses", meses: 3, gastoMensual: 1500, importe: 4500, productos: ["cta"] },
    { id: "c4", nombre: "Imprevistos", modo: "importe", importe: 1500, productos: [] },
  ];
  const r = C.resumenColchones(prods, fondos);
  const por = Object.fromEntries(r.fondos.map(f => [f.id, f]));
  assert.equal(por.c1.tiene, 5000);
  assert.equal(por.c1.falta, 1000);
  cerca(por.c1.pct, 0.833);
  assert.equal(por.c2.tiene, 21000);                 // monetario + RF ultra corto
  assert.equal(por.c2.sobra, 1000);                  // lo que sobra se queda en su fondo
  assert.equal(por.c2.falta, 0);
  assert.equal(por.c2.pct, 1);
  assert.deepEqual(por.c2.prods.map(p => p.id), ["mon2", "rfuc"]);
  cerca(por.c3.mesesCubiertos, 2);
  assert.equal(por.c3.meses, 3);                     // lo que pide el fondo no cambia
  assert.equal(por.c4.tiene, 1500);                  // sin productos: de la liquidez libre
  assert.ok(por.c4.deLiquidez);
  assert.deepEqual(r.libres.map(p => p.id), ["libre"]);
  assert.equal(r.liquidezLibre, 4000);
  assert.equal(r.disponible, 2500);                  // lo que queda de la libre
  assert.equal(r.objetivo, 32000);
  assert.equal(r.falta, 2500);                       // 1000 del personal + 1500 de la familia
});

test("varios fondos: los que no tienen productos se reparten la liquidez por orden", () => {
  const prods = [{ id: "a", tipoClave: "efectivo", valor: 3000 }];
  const r = C.resumenColchones(prods, [
    { id: "c1", importe: 2000, productos: [] }, { id: "c2", importe: 2000, productos: [] }]);
  assert.deepEqual(r.fondos.map(f => f.tiene), [2000, 1000]);
  assert.equal(r.disponible, 0);
  assert.equal(r.falta, 1000);
  // Un producto que ya no está (borrado, o de otro perfil) no cuenta, pero el fondo sigue siendo «con productos».
  const s = C.resumenColchones(prods, [{ id: "c1", importe: 2000, productos: ["no_esta"] }]);
  assert.equal(s.fondos[0].tiene, 0);
  assert.equal(s.disponible, 3000);
  assert.deepEqual(C.resumenColchones(prods, []).fondos, []);
});

const RV = "Renta variable", RF = "Renta fija";
const O = { por: "clase", pesos: { [RV]: 80, [RF]: 20 }, vigilar: 3, rebalancear: 5, conEfectivo: false };
const CARTERA = [
  { clase: "RV Global Cap. Grande Blend", valor: 6000, tipoClave: "fondo" },
  { clase: "RV Global Emergente", valor: 2000, tipoClave: "fondo" },
  { valor: 500, tipoClave: "accion", clase: "Renta variable" },
  { clase: "RF Diversificada EUR", valor: 1500, tipoClave: "fondo" },
  { clase: "Efectivo", valor: 5000, tipoClave: "efectivo" },                           // no cuenta: sin %
  { clase: "RV Global", valor: 999, tipoClave: "fondo", largoPlazo: false },           // no cuenta
];

test("reparto objetivo: grupos, desviación y semáforo", () => {
  const grupos = C.gruposReparto(CARTERA, O);
  assert.deepEqual(grupos.map(g => [g.nombre, g.valor]), [[RV, 8500], [RF, 1500]]);   // toda la bolsa junta
  assert.equal(grupos[0].productos.length, 3);
  const { total, filas, peor } = C.filasReparto(grupos, O);
  assert.equal(total, 10000);
  assert.deepEqual(filas.map(f => f.nombre), [RV, RF]);
  cerca(filas[0].desv, 5);
  assert.equal(filas[0].estado, "vigilar");           // 5 puntos: aún «vigilar»
  cerca(filas[1].cuadrar, 500);
  assert.equal(peor.nombre, RV);
  const mucho = C.filasReparto(C.gruposReparto([{ clase: "RV", valor: 9000 }, { clase: "RF", valor: 1000 }], O), O);
  assert.equal(mucho.filas[0].estado, "rebalancear");
  const conCuentas = C.gruposReparto(CARTERA, { ...O, conEfectivo: true });
  assert.ok(conCuentas.some(g => g.nombre === "Efectivo"));
  const falta = C.gruposReparto([{ clase: "RV", valor: 100 }], O);
  assert.deepEqual(falta.map(g => [g.nombre, g.valor]), [[RV, 100], [RF, 0]]);   // el que aún no tienes, a 0
});

test("reparto objetivo: lo que eliges a mano manda sobre la regla general", () => {
  const lista = [
    { id: "w", corto: "World", clase: "RV Global", valor: 800, tipoClave: "fondo" },
    { id: "b", corto: "Bitcoin", valor: 100, tipoClave: "cripto" },
    { id: "m", corto: "Monetario", clase: "Monetario EUR", valor: 300, tipoClave: "fondo", largoPlazo: false },
    { id: "c", corto: "Cuenta", valor: 500, tipoClave: "efectivo" },
    { id: "d", corto: "Hipoteca", valor: 900, tipoClave: "deuda" },
  ];
  const o = { por: "clase", pesos: { [RV]: 90, Monetario: 10 }, vigilar: 3, rebalancear: 5,
    cuenta: { b: false, m: true, d: true } };
  assert.equal(C.cuentaPorDefecto(lista[1], o), true);       // la regla general sí la contaría
  assert.equal(C.cuentaEnReparto(lista[1], o), false);       // pero la has quitado
  assert.equal(C.cuentaEnReparto(lista[2], o), true);        // el monetario a corto plazo, metido a mano
  assert.equal(C.cuentaEnReparto(lista[3], o), false);       // la cuenta: sin % y sin elegirla
  assert.equal(C.cuentaEnReparto(lista[4], o), false);       // las deudas nunca
  assert.deepEqual(C.gruposReparto(lista, o).map(g => [g.nombre, g.valor]), [[RV, 800], ["Monetario", 300]]);
});

test("reparto objetivo: tipos de activo sencillos", () => {
  const t = p => C.tipoReparto(p);
  assert.equal(t({ tipoClave: "fondo", clase: "Mercado Monetario Corto Plazo EUR" }), "Monetario");
  assert.equal(t({ tipoClave: "fondo", clase: "RF Bonos Gobierno EUR" }), RF);
  assert.equal(t({ tipoClave: "fondo", clase: "Mixtos Moderados EUR" }), "Mixtos");
  assert.equal(t({ tipoClave: "etf", clase: "Global Large-Cap Blend Equity" }), RV);
  assert.equal(t({ tipoClave: "etf" }), RV);
  assert.equal(t({ tipoClave: "cripto", clase: "Criptoactivos" }), "Criptoactivos");
  assert.equal(t({ tipoClave: "efectivo", clase: "Efectivo" }), "Efectivo");
  assert.equal(t({ tipoClave: "pension", clase: "Jubilación" }), "Planes de pensiones");
  assert.equal(t({ tipoClave: "pension", clase: "RV Global Cap. Grande Blend" }), RV);
  assert.equal(t({ tipoClave: "fondo", clase: "Fondos" }), "Otros");
});

test("reparto objetivo: uno guardado por categoría se suma en su tipo, y el efectivo con % cuenta", () => {
  const viejo = { por: "clase", vigilar: 3, rebalancear: 5, conEfectivo: false,
    pesos: { "RV Global Cap. Grande Blend": 60, "RV Global Emergente": 20, "Mercado Monetario Corto Plazo EUR": 10, Efectivo: 10 } };
  const o = C.normalizaReparto(viejo);
  assert.deepEqual(o.pesos, { [RV]: 80, Monetario: 10, Efectivo: 10 });
  assert.equal(o.conEfectivo, true);
  const g = C.gruposReparto([...CARTERA, { clase: "Mercado Monetario Corto Plazo EUR", valor: 1000, tipoClave: "fondo" }], viejo);
  assert.deepEqual(g.map(x => [x.nombre, x.valor]).sort(), [["Efectivo", 5000], ["Monetario", 1000], [RF, 1500], [RV, 9499]].sort());
  // Por producto no se toca; y una cuenta con % cuenta, sin % no.
  const porProd = { por: "producto", pesos: { Cuenta: 10, World: 90 }, vigilar: 3, rebalancear: 5 };
  assert.equal(C.normalizaReparto(porProd), porProd);
  const lista = [{ corto: "World", valor: 900, tipoClave: "fondo" }, { corto: "Cuenta", valor: 100, tipoClave: "efectivo" },
    { corto: "Otra", valor: 50, tipoClave: "efectivo" }];
  assert.deepEqual(C.gruposReparto(lista, porProd).map(x => x.nombre).sort(), ["Cuenta", "World"]);
});

test("reparto objetivo: la aportación va a lo que falta, sin vender", () => {
  const grupos = [{ nombre: RV, valor: 8500 }, { nombre: RF, valor: 1500 }];
  // Con 500 €: el objetivo de RF es 20 % de 10.500 = 2.100 → le faltan 600; todo a RF.
  const r = C.repartirAportacion(grupos, O.pesos, 500);
  cerca(r[0], 0); cerca(r[1], 500);
  // Con 5.000 €: total 15.000 → RV 12.000 (faltan 3.500), RF 3.000 (faltan 1.500): justo cuadra.
  const r2 = C.repartirAportacion(grupos, O.pesos, 5000);
  cerca(r2[0], 3500); cerca(r2[1], 1500);
  // Si sobra después de cuadrar, el resto va según el objetivo; siempre suma lo aportado.
  const r3 = C.repartirAportacion([{ nombre: RV, valor: 800 }, { nombre: RF, valor: 200 }], O.pesos, 1000);
  cerca(r3[0], 800); cerca(r3[1], 200);
  for (const a of [1, 333, 1900, 25000]) cerca(C.repartirAportacion(grupos, O.pesos, a).reduce((x, y) => x + y, 0), a);
  assert.deepEqual(C.repartirAportacion(grupos, O.pesos, 0), [0, 0]);
  assert.deepEqual(C.repartirAportacion(grupos, O.pesos, NaN), [0, 0]);
});

test("aportaciones periódicas: avisa de las que faltan desde la última", () => {
  const ids = ["a", "b"];
  const lista = [
    { producto: "a", importe: 200, dia: 5, ultima: "2026-08-05" },     // faltan sep y oct
    { producto: "b", importe: 50, dia: 31, ultima: "2026-01-31" },     // meses cortos: el último día
    { producto: "zz", importe: 10, dia: 1, ultima: "2026-01-01" },     // producto borrado: nada
    { producto: "a", importe: 10, dia: 20, ultima: "2026-09-20" },     // la de octubre aún no toca
  ];
  const p = C.periodicasPendientes(lista, ids, "2026-10-16");
  assert.deepEqual(p[0], { producto: "a", importe: 200, dia: 5, desde: "2026-09-05", cuantas: 2 });
  assert.equal(p[1].desde, "2026-02-28");
  assert.equal(p[1].cuantas, 8);                                       // feb a sep (el 31-oct aún no)
  assert.equal(p.length, 2);
  assert.deepEqual(C.periodicasPendientes(undefined, ids, "2026-10-16"), []);
  assert.deepEqual(C.periodicasPendientes([{ producto: "a", dia: 5, ultima: "<script>" }], ids, "2026-10-16"), []);
});

// Un año inventado: índice que sube 1 punto al mes, y un mes de octubre en curso.
function datosDeMeses() {
  const fechas = [], indice = [];
  const dias = ["2025-12-31", "2026-01-31", "2026-02-27", "2026-03-31", "2026-04-30", "2026-05-29", "2026-06-30",
    "2026-07-31", "2026-08-31", "2026-09-30", "2026-10-15"];
  dias.forEach((f, i) => { fechas.push(f); indice.push(100 + i); });
  const resumenMensual = ["2026-08", "2026-09", "2026-10"].map((mes, i) => ({
    mes, inicio: 10000 + i * 500, fin: 10500 + i * 500, aportado: i === 2 ? 0 : 300, mercado: 200, nuevo: 0, rentabilidad: 0.02,
  }));
  return { fechas, indiceCartera: indice, resumenMensual, fechaExtracto: "2026-10-15", total: { tir: 0.091 } };
}

test("compartir mi mes: las cifras del mes, del año y la racha", () => {
  const D = datosDeMeses();
  const d = C.resumenParaCompartir(D);                 // por defecto, el último mes
  assert.equal(d.mes, "2026-10");
  assert.equal(d.etiqueta, "Octubre 2026");
  assert.equal(d.enCurso, true);                       // datos al 15: el mes no ha acabado
  assert.equal(d.rentMes, 0.02);
  assert.ok(Math.abs(d.anoPct - 0.10) < 1e-9);         // de 100 (31-dic) a 110
  assert.deepEqual(d.serieAno, [100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110]);
  assert.equal(d.etqIni, "Enero");
  assert.equal(d.racha, 2);                            // octubre aún sin aportar: cuenta ago y sep
  assert.equal(d.tir, 0.091);
  assert.ok(Math.abs(d.crecimiento - 500 / 11000) < 1e-9);
  const sep = C.resumenParaCompartir(D, 1);            // un mes ya cerrado
  assert.equal(sep.enCurso, false);
  assert.equal(sep.tir, null);                         // la TIR es de hoy, no de septiembre
  assert.ok(Math.abs(sep.anoPct - 0.09) < 1e-9);
  assert.equal(C.resumenParaCompartir({ resumenMensual: [] }), null);
});

test("compartir mi mes: si empezaste este año, la curva sale desde tu primer día", () => {
  const D = datosDeMeses();
  D.fechas = D.fechas.slice(4);                        // empieza el 30 de abril
  D.indiceCartera = D.indiceCartera.slice(4);
  const d = C.resumenParaCompartir(D);
  assert.equal(d.etqIni, "Abril");
  assert.equal(d.serieAno[0], 104);
  assert.ok(Math.abs(d.anoPct - (110 / 104 - 1)) < 1e-9);
});

test("proyección: sin inflación, como siempre; en euros de hoy, descontada", () => {
  const base = { valor: 10000, aportado: 8000, anos: 10, rent: 0.07, aporte: 500, desde: "2026-10-25" };
  const p = C.proyeccion(base);
  assert.equal(p.fechas.length, 121);
  assert.equal(p.fechas[0], "2026-10-01");
  assert.equal(p.valores[0], 10000);
  assert.equal(p.aportado[120], 8000 + 500 * 120);
  // Cada mes crece la rentabilidad/12 y entra la aportación, como hacía el panel.
  let v = 10000;
  for (let i = 0; i < 120; i++) v = v * (1 + 0.07 / 12) + 500;
  assert.equal(p.valores[120], Math.round(v));
  assert.deepEqual(C.proyeccion({ ...base, inflacion: 0 }), p);

  // En euros de hoy: cada importe se divide por lo que han subido los precios hasta su mes.
  const r = C.proyeccion({ ...base, inflacion: 0.02 });
  const def = Math.pow(1 + 0.02 / 12, 120);
  cerca(r.valores[120], v / def, 1);
  let ap = 8000;
  for (let k = 1; k <= 120; k++) ap += 500 / Math.pow(1 + 0.02 / 12, k);
  cerca(r.aportado[120], ap, 1);
  assert.ok(r.valores[120] < p.valores[120] && r.aportado[120] < p.aportado[120]);
  assert.equal(r.valores[0], 10000);                    // hoy, un euro es un euro

  // Si la cartera rinde justo la inflación, sin aportar, en euros de hoy no se mueve.
  const q = C.proyeccion({ valor: 1000, aportado: 1000, anos: 30, rent: 0.03, aporte: 0, inflacion: 0.03, desde: "2026-01-15" });
  assert.ok(q.valores.every(x => Math.abs(x - 1000) <= 1));
});

test("vistaComparacion: toda la cartera o solo largo plazo", () => {
  const largo = { tuValor: 10, referencias: [{ id: "mundo" }] };
  const comp = { tuValor: 20, referencias: [{ id: "mundo" }], soloLargoPlazo: largo };
  assert.deepEqual(C.vistaComparacion(comp, "largo"), { hayOpcion: true, grupo: "largo", datos: largo });
  assert.deepEqual(C.vistaComparacion(comp, "todo"), { hayOpcion: true, grupo: "todo", datos: comp });
  assert.equal(C.vistaComparacion(comp, null).grupo, "todo");          // por defecto, toda la cartera
  // Sin la versión de largo plazo (todo lo es, o nada), no hay que elegir: toda la cartera.
  const sin = { tuValor: 20, referencias: [{ id: "mundo" }], soloLargoPlazo: null };
  assert.deepEqual(C.vistaComparacion(sin, "largo"), { hayOpcion: false, grupo: "todo", datos: sin });
  // Datos de una versión anterior de la app, sin el campo.
  assert.equal(C.vistaComparacion({ referencias: [] }, "largo").hayOpcion, false);
});
