// =====================================================================
// CondoHub · Agentes · MongoDB (base "agentes")
// Reglas: G1–G3, F5 (docs/negocio/reglas-de-negocio.md)
// Uso: mongosh "mongodb://localhost:27017" db/mongo-init.js
//      (otra base, p. ej. para pruebas: AGENTES_DB=agentes_pruebas mongosh ... db/mongo-init.js)
// Idempotente: crea colecciones e índices solo si faltan; si existen, actualiza el validador.
// =====================================================================

const ag = db.getSiblingDB(process.env.AGENTES_DB || 'agentes');   // AGENTES_DB=agentes_pruebas para las pruebas de integración

function asegurar(nombre, schema) {
  const existe = ag.getCollectionNames().includes(nombre);
  const opciones = { validator: { $jsonSchema: schema }, validationLevel: 'strict', validationAction: 'error' };
  if (existe) ag.runCommand({ collMod: nombre, ...opciones });
  else ag.createCollection(nombre, opciones);
}

// ---------------------------------------------------------------------
// misiones (agregado Mision · G1)
// ---------------------------------------------------------------------
asegurar('misiones', {
  bsonType: 'object',
  required: ['tipo', 'objetivo', 'estado', 'iniciadaPor', 'pasosEjecutados', 'limitePasos', 'creadaEn'],
  properties: {
    tipo: { enum: ['GESTIONAR_MOROSIDAD', 'LIBRE'] },
    objetivo: { bsonType: 'string', description: 'ej. "Gestiona la morosidad de octubre 2026"' },
    parametros: { bsonType: 'object', description: 'ej. {periodo: "2026-10", bloque: "B"}' },
    estado: { enum: ['EN_CURSO', 'ESPERANDO_CONFIRMACION', 'COMPLETADA', 'INCOMPLETA', 'CANCELADA', 'ERROR'] },
    iniciadaPor: { bsonType: 'string', description: 'sub del ADMIN' },
    modeloLlm: { bsonType: 'string' },
    pasosEjecutados: { bsonType: ['int', 'long'], minimum: 0 },
    limitePasos: { bsonType: ['int', 'long'], minimum: 1, maximum: 50 },
    resumen: { bsonType: 'string' },
    creadaEn: { bsonType: 'date' },
    terminadaEn: { bsonType: ['date', 'null'] },
  },
});
ag.misiones.createIndex({ estado: 1, creadaEn: -1 });
ag.misiones.createIndex({ iniciadaPor: 1, creadaEn: -1 });

// ---------------------------------------------------------------------
// confirmaciones (G2): toda herramienta que no es de lectura espera al ADMIN
// ---------------------------------------------------------------------
asegurar('confirmaciones', {
  bsonType: 'object',
  required: ['misionId', 'herramienta', 'argumentos', 'riesgo', 'estado', 'creadaEn'],
  properties: {
    misionId: { bsonType: 'objectId' },
    herramienta: { bsonType: 'string' },
    argumentos: { bsonType: 'object' },
    justificacion: { bsonType: 'string', description: 'por qué el agente quiere ejecutarla' },
    riesgo: { enum: ['ESCRITURA', 'DINERO'] },
    estado: { enum: ['PENDIENTE', 'APROBADA', 'RECHAZADA', 'EJECUTADA', 'FALLIDA'] },
    resueltaPor: { bsonType: ['string', 'null'] },
    resueltaEn: { bsonType: ['date', 'null'] },
    resultado: { bsonType: ['object', 'null'] },
    creadaEn: { bsonType: 'date' },
  },
  // G2: no se ejecuta nada que no haya aprobado un ADMIN identificado
  anyOf: [
    { properties: { estado: { enum: ['PENDIENTE'] } } },
    { required: ['resueltaPor', 'resueltaEn'],
      properties: { estado: { enum: ['APROBADA', 'RECHAZADA', 'EJECUTADA', 'FALLIDA'] },
                    resueltaPor: { bsonType: 'string' }, resueltaEn: { bsonType: 'date' } } },
  ],
});
ag.confirmaciones.createIndex({ estado: 1, creadaEn: 1 });
ag.confirmaciones.createIndex({ misionId: 1 });

// ---------------------------------------------------------------------
// bitacora (G3): cada paso del agente, solo se agrega
// ---------------------------------------------------------------------
asegurar('bitacora', {
  bsonType: 'object',
  required: ['misionId', 'paso', 'tipo', 'fecha'],
  properties: {
    misionId: { bsonType: 'objectId' },
    paso: { bsonType: ['int', 'long'], minimum: 1 },
    tipo: { enum: ['RAZONAMIENTO', 'LLAMADA_HERRAMIENTA', 'RESULTADO_HERRAMIENTA', 'CONFIRMACION', 'ERROR', 'FIN'] },
    herramienta: { bsonType: 'string' },
    entrada: { bsonType: 'object' },
    salida: { bsonType: 'object' },
    confirmacionId: { bsonType: 'objectId' },
    confirmadoPor: { bsonType: 'string' },
    tokens: { bsonType: 'object' },
    fecha: { bsonType: 'date' },
  },
});
ag.bitacora.createIndex({ misionId: 1, paso: 1 });

// ---------------------------------------------------------------------
// memoria: lo que el agente recuerda entre misiones (por unidad o global)
// ---------------------------------------------------------------------
asegurar('memoria', {
  bsonType: 'object',
  required: ['ambito', 'clave', 'contenido', 'actualizadaEn'],
  properties: {
    ambito: { enum: ['GLOBAL', 'UNIDAD'] },
    clave: { bsonType: 'string', description: 'ej. unidad B-101 o "politica-recordatorios"' },
    contenido: { bsonType: 'string', description: 'ej. "prometió pagar el 20/10; plan de 3 cuotas propuesto"' },
    misionOrigen: { bsonType: 'objectId' },
    actualizadaEn: { bsonType: 'date' },
    expiraEn: { bsonType: ['date', 'null'] },
  },
});
ag.memoria.createIndex({ ambito: 1, clave: 1 }, { unique: true });
ag.memoria.createIndex({ expiraEn: 1 }, { expireAfterSeconds: 0, partialFilterExpression: { expiraEn: { $type: 'date' } } });

// ---------------------------------------------------------------------
// metricas e informes (G5): lo que lee y produce el agente de monitoreo. Solo se agregan.
// ---------------------------------------------------------------------
const metricasDoc = {
  bsonType: 'object',
  required: ['generadaEn', 'unidadesMorosas', 'deudaVencida', 'pagosPendientes'],
  properties: {
    generadaEn: { bsonType: 'date' },
    unidadesMorosas: { bsonType: ['int', 'long'], minimum: 0 },
    deudaVencida: { bsonType: 'decimal', description: 'Decimal128, nunca double (F10)' },
    pagosPendientes: { bsonType: ['int', 'long'], minimum: 0 },
    diasPagoMasAntiguo: { bsonType: ['int', 'long', 'null'], minimum: 0 },
  },
};
asegurar('metricas', metricasDoc);
ag.metricas.createIndex({ generadaEn: -1 });

asegurar('informes', {
  bsonType: 'object',
  required: ['informeId', 'generadoEn', 'origen', 'metricas', 'alertas', 'resumen', 'lineaBase', 'notificado'],
  properties: {
    informeId: { bsonType: 'string', description: 'uuid del informe' },
    generadoEn: { bsonType: 'date' },
    origen: { enum: ['PROGRAMADO', 'MANUAL'] },
    metricas: metricasDoc,
    alertas: {
      bsonType: 'array',
      items: {
        bsonType: 'object',
        required: ['tipo', 'severidad', 'mensaje'],
        properties: {
          tipo: { enum: ['MOROSIDAD_CRECIENTE', 'DEUDA_VENCIDA_CRECIENTE', 'PAGOS_SIN_CONCILIAR'] },
          severidad: { enum: ['MEDIA', 'ALTA'] },
          mensaje: { bsonType: 'string' },
          valor: { bsonType: 'string' },
          referencia: { bsonType: 'string' },
        },
      },
    },
    resumen: { bsonType: 'string' },
    lineaBase: { bsonType: 'bool' },
    notificado: { bsonType: 'bool' },
  },
});
ag.informes.createIndex({ informeId: 1 }, { unique: true });
ag.informes.createIndex({ generadoEn: -1 });

print('Base "agentes" lista');
