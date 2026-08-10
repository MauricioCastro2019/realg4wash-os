# Mi Auto Pro 0.2 — Memory Engine

## Tesis

Mi Auto Pro no pide al usuario que capture manualmente la vida de su auto. Reconstruye memoria desde fuentes que ya existen y después mantiene esa memoria viva.

WhatsApp, notas, facturas, fotos, órdenes, escáner OBD y servicios conectados son **fuentes**. No son el expediente canónico.

El expediente canónico es un conjunto de eventos estructurados, verificables y con procedencia.

## Flujo CenterFix / Andrés

1. Taller crea una invitación para un vehículo.
2. Dueño recibe link/QR privado.
3. Dueño acepta términos y define permisos del taller.
4. Dueño puede importar su chat completo con el taller (idealmente export sin multimedia).
5. Taller puede aportar notas, fotografías y órdenes que ya posee legítimamente.
6. Memory Engine detecta eventos candidatos.
7. Usuario revisa y confirma.
8. Eventos confirmados alimentan Vehicle Passport, Health, costos, Issues y próximas acciones.

## Principio de consentimiento

Un taller puede invitar y aportar información propia, pero no se convierte en dueño del expediente.

El dueño controla:
- acceso al Garage;
- qué proveedores están vinculados;
- qué información se comparte;
- revocación de acceso;
- exportación del Vehicle Passport.

La futura persistencia debe registrar el alcance y fecha de cada autorización.

## Provenance / Trust Model

Cada dato debe poder responder:

- ¿de dónde vino?
- ¿quién lo aportó?
- ¿fue extraído o inferido?
- ¿qué evidencia existe?
- ¿quién lo confirmó?
- ¿puede modificarse sin perder el original?

Estados sugeridos:

- `ai_candidate`: extracción/inferencia pendiente de revisión.
- `owner_confirmed`: confirmado por dueño.
- `provider_confirmed`: confirmado por proveedor autorizado.
- `evidence_verified`: respaldado por documento/orden/evidencia con hash.
- `disputed`: fuentes o personas discrepan.

## Modelo futuro

### vehicles
Identidad estable del activo.

### vehicle_events
- id
- vehicle_id
- occurred_at
- odometer_km
- category
- title
- description
- total_cost
- currency
- provider_id
- verification_status
- created_by

### event_items
Piezas, mano de obra, consumibles y montos unitarios.

### vehicle_issues
Problemas abiertos/cerrados; códigos OBD pueden relacionarse con varios eventos.

### source_artifacts
- tipo: whatsapp/pdf/image/order/obd/etc.
- storage reference
- sha256
- original filename
- captured_at
- source_actor
- visibility

### event_evidence
Relación N:M entre eventos y fuentes.

### import_sessions
Una importación puede contener cientos de mensajes y producir varios eventos candidatos.

### consents
- owner_id
- provider_id
- vehicle_id
- scope
- granted_at
- revoked_at

## Importación de WhatsApp

### Fase barata
Se procesa primero el texto completo.

Se extraen:
- fechas;
- participantes;
- montos;
- kilometrajes;
- códigos Pxxxx;
- palabras/señales mecánicas;
- referencias a multimedia.

Los mensajes relevantes se agrupan por ventana temporal para formar candidatos.

### Fase inteligente
Sólo se manda a IA:
- grupos ambiguos;
- notas/fotos asociadas a candidatos relevantes;
- documentos que no admiten extracción determinista.

Esto evita mandar cientos de fotos o años de conversación innecesariamente.

## Importación de notas de Andrés

Las notas tienen gran valor porque normalmente contienen simultáneamente:
- fecha;
- kilometraje;
- conceptos;
- costo;
- diagnósticos;
- pendientes.

Una fotografía puede convertirse en un evento candidato mediante Vision AI, pero el documento original siempre debe conservarse como evidencia.

## Experiencia deseada

El usuario no ve una tabla de ingestión.

Ve:

> Encontré 12 posibles visitas a taller entre 2024 y 2026.
> 8 tienen costo.
> 6 tienen kilometraje.
> 3 contienen códigos OBD.
> Encontré 17 fotos relacionadas.
>
> Revisemos las de mayor impacto primero.

Cada tarjeta se puede aceptar, editar, fusionar con otra o descartar.

## Virtual Garage

La visualización 3D no es decoración. Debe convertirse en otra interfaz del modelo de datos.

Ejemplos:
- tocar motor → Issues + eventos + salud + costos;
- tocar rueda delantera → llanta, freno, suspensión y último servicio;
- cambiar fecha → ver estado histórico del vehículo;
- alternar capas → mecánica / estética / documentos / modificaciones.

Fases:
1. hotspots y representación genérica interactiva;
2. modelo 3D por familia/modelo de vehículo;
3. personalización color/rines/modificaciones;
4. fotogrametría o reconstrucción del vehículo real cuando tenga sentido;
5. AR/VR como superficie adicional, no como núcleo de negocio.

## Regla de producto

La gamificación premia mejor información y mejor cuidado; nunca más gasto ni más uso del vehículo.

## Próximo bloque técnico

1. Validar Import Lab con export real de WhatsApp y notas reales.
2. Conectar base propia de Mi Auto Pro.
3. Persistir import sessions + artifacts + candidates.
4. Implementar revisión/merge/confirmación.
5. Crear invitaciones reales para CenterFix.
6. Convertir el Garage a datos persistentes.
7. Construir primera capa interactiva del Virtual Garage.
