# Mi Auto Pro 0.1 — The Garage

## Decisión de producto

Mi Auto Pro no será una agenda de mantenimientos. Será la memoria operativa e inteligente del vehículo.

La entidad principal deja de ser la orden de servicio y pasa a ser el **vehículo**. RealG4Wash, talleres, llanteras, aseguradoras y otros proveedores alimentan su historial, pero no son el centro de la experiencia.

## Promesa

> Todo lo importante que le ha pasado a tu auto, entendido y utilizable en un solo lugar.

El usuario debe poder responder sin reconstruir conversaciones, tickets o PDFs:

- ¿Qué le ha pasado a mi coche?
- ¿Cuánto le he gastado?
- ¿Qué problemas se repiten?
- ¿Qué sigue pendiente?
- ¿Qué reparación provocó o no provocó un problema posterior?
- ¿Vale la pena seguir invirtiendo en él?
- ¿Qué puedo demostrar cuando lo venda o cambie de taller?

## Principios

1. **Vehicle-first.** El vehículo es el objeto persistente; los servicios son eventos de su vida.
2. **Memoria antes que recordatorios.** Primero construir un expediente confiable. Después automatizar mantenimiento.
3. **Gamificación útil.** Health, niveles y misiones deben representar cuidado real del activo, no uso compulsivo de la app.
4. **Trazabilidad.** Cada evento debe conservar fecha, kilometraje, costo, proveedor, evidencia, diagnóstico, piezas y pendientes.
5. **IA para eliminar captura manual.** Foto/PDF/ticket/conversación → propuesta de evento estructurado → confirmación humana.
6. **Proveedor-neutral.** RealG4Wash es el primer vertical conectado, no el dueño del expediente.
7. **Privacidad por diseño.** El propietario decide qué parte del Vehicle Passport comparte.

## Vertical slice 0.1

La ruta `/garage` valida la experiencia usando un Volkswagen Gol 2015 sanitizado como caso real:

- Hero de vehículo / identidad de garage.
- Vehicle Health 0–100 calculado por sistemas ponderados.
- Estado de motor, enfriamiento, frenos, suspensión, eléctrico y expediente.
- Inversión documentada y costo por kilómetro rastreado.
- Códigos / alertas abiertas.
- Misiones de mantenimiento y documentación.
- Distribución del gasto por categoría.
- Vehicle Passport cronológico.
- Prototipo de interacción para importar registros con IA.

Esta iteración es intencionalmente **sin migraciones de base de datos**. Primero se valida información, jerarquía visual y sensación del producto sin comprometer RealG4Wash OS.

## Modelo de datos objetivo

### Vehicle

- owner_id
- VIN
- plate
- make / model / year / trim
- odometer
- acquisition_date / acquisition_price
- status
- primary_photo

### VehicleEvent

Ledger universal para cualquier hecho relevante:

- vehicle_id
- occurred_at
- odometer
- event_type
- category
- title
- description
- provider_id
- total_cost
- source_type
- source_document_id
- confidence
- verified_by_owner

### EventItem

- event_id
- item_type (`part`, `labor`, `fluid`, `diagnostic`, `fee`)
- name
- brand
- part_number
- quantity
- unit_cost
- warranty_until

### VehicleIssue

- vehicle_id
- opened_at
- closed_at
- code
- system
- severity
- description
- source_event_id
- resolution_event_id
- status

### VehicleDocument

- vehicle_id
- document_type
- file
- issued_at
- expires_at
- extracted_data
- verified

### Provider

- name
- provider_type
- contact
- reputation metadata

## Health Score

El score no debe ser arbitrario. La Alpha usa pesos explícitos por sistema para validar la interfaz. La versión persistente deberá calcularlo a partir de:

- fallas abiertas y severidad;
- mantenimiento vencido;
- inspecciones recientes;
- reincidencias;
- kilometraje desde servicio;
- documentación crítica vigente;
- señales OBD cuando existan.

El usuario siempre debe poder abrir el score y entender **por qué** tiene ese número.

## Vehicle Passport

El Passport es una vista derivada del ledger, no otra base paralela. Debe permitir:

- historial cronológico;
- filtros por sistema / proveedor / gasto;
- evidencia adjunta;
- nivel de completitud;
- exportación o enlace compartible con permisos;
- historial de kilometraje y detección de inconsistencias.

## IA: Import Pipeline

1. Usuario sube foto, PDF, ticket o texto.
2. Clasificador identifica tipo de documento.
3. Extractor produce JSON estructurado.
4. Motor intenta asociar vehículo, proveedor y eventos previos.
5. Detector de continuidad marca reincidencias o contradicciones.
6. Usuario revisa y confirma.
7. Se guarda archivo original + evento estructurado + procedencia.

La IA propone; el expediente conserva procedencia y confirmación.

## Relación con RealG4Wash

RealG4Wash OS conserva su responsabilidad B2B: operar el autolavado.

Cuando una orden se completa, podrá publicar un `VehicleEvent` al expediente Mi Auto Pro del cliente con:

- fecha;
- kilometraje;
- servicio;
- costo;
- inspección;
- fotos antes/después.

El mismo contrato podrá usarlo después CenterFix u otro taller.

## Siguiente bloque de ejecución

Después de validar la Alpha:

1. Extraer Mi Auto Pro a su propio dominio/repositorio o convertirlo en bounded context separado.
2. Crear modelos persistentes `VehicleEvent`, `VehicleIssue` y `VehicleDocument`.
3. Migrar el Gol sanitizado desde datos hardcodeados a seed estructurado.
4. Construir CRUD de eventos y adjuntos.
5. Implementar Import Lab con extracción IA.
6. Conectar órdenes RealG4Wash → VehicleEvent.
7. Agregar autenticación orientada a propietarios, no operadores.

## Métrica de éxito de 0.1

La Alpha funciona si, al verla, el propietario siente dos cosas:

1. **“Ese es mi coche.”**
2. **“Ahora sí entiendo su historia y qué debo hacer con él.”**

Todo lo demás es secundario.
