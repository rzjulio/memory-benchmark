# Guia de ejecucion del benchmark data-kb

Esta guia explica como ejecutar el benchmark, que puede hacer la IA, que debes configurar tu, y que pasos seguir para obtener conclusiones confiables.

## Respuesta corta

El benchmark no se ejecuta solo por tener los archivos JSONL.

Hay tres formas de correrlo:

| Modo | Quien ejecuta | Cuando usarlo |
|---|---|---|
| Manual supervisado | Tu ejecutas comandos y llenas resultados | Si aun no tienes runner o quieres validar el proceso una vez. |
| IA-asistido | La IA ejecuta comandos, captura resultados y genera reporte | Si la IA tiene acceso al repo, al comando `data-kb` y a la base de prueba. |
| Runner automatizado | Un script ejecuta todo y genera metricas/reporte | Ideal para regresion, CI y comparaciones repetibles. |

La mejor opcion final es **runner automatizado + revision humana selectiva**.

## Que puede ejecutar la IA

La IA puede ejecutar el benchmark si tiene acceso a:

- el codigo o binario de `data-kb`;
- una base limpia SQLite o PostgreSQL de prueba;
- comandos reales para reset, import, recall, capture/export;
- logs o salida JSON con IDs de memorias recuperadas/guardadas;
- usage de tokens del modelo, o al menos un tokenizador estimado;
- permiso para crear archivos de resultados en `runs/`.

La IA puede hacer bien:

- cargar memorias semilla;
- correr queries;
- capturar top-k de retrieval;
- calcular precision@k, recall@k, MRR, leaks y forbidden hits;
- ejecutar workflows baseline vs `data-kb`;
- generar `metrics.json` y `report.md`;
- marcar casos que requieren revision humana.

La IA no debe decidir sola todo el benchmark. Debe dejar evidencia y marcar para revision:

- casos con secretos o PII;
- scope leaks;
- respuestas inventadas en casos sin evidencia;
- scores bajos o dudosos;
- casos donde `data-kb` ahorra tokens pero baja calidad;
- cambios de umbrales.

## Lo que falta conectar

El kit ya trae datos y criterios, pero no conoce los comandos exactos de tu instalacion de `data-kb`.

Debes mapear estas operaciones:

| Operacion | Comando real a conectar |
|---|---|
| Reset DB | Comando para crear una corrida limpia. |
| Import memory | Comando para guardar una memoria desde JSON. |
| Recall/query | Comando para consultar memoria y devolver top-k IDs. |
| Capture/analyze | Comando para probar si un input se guarda, rechaza, actualiza o fusiona. |
| Export/list | Comando para listar memorias guardadas y metadata. |
| Metrics/logs | Forma de obtener tokens, latencia y errores. |

Ejemplo conceptual:

```bash
# No es un comando garantizado. Ajustalo a la CLI real de data-kb.
data-kb memory persist --json '<memory-json>'
data-kb tool --json '<query-json>'
data-kb memory list --json
```

## Preparacion

1. Instala o activa `data-kb`.
2. Elige backend:
   - SQLite para primera corrida local.
   - PostgreSQL para validar comportamiento robusto.
3. Crea una base de datos aislada para el benchmark.
4. Define un `RUN_ID`, por ejemplo:

```text
2026-06-11-run-001
```

5. Crea carpeta de salida:

```text
runs/2026-06-11-run-001/
```

6. Copia o referencia estos archivos:

```text
seeds/memories.jsonl
cases/retrieval_cases.jsonl
cases/workflow_cases.jsonl
cases/capture_cases.jsonl
stress/noise_memories.jsonl
stress/adversarial_retrieval_cases.jsonl
stress/longitudinal_memory_cases.jsonl
stress/capture_abuse_cases.jsonl
stress/scale_test_plan.json
```

## Fase 0: Smoke test

Antes de correr todo, valida que `data-kb` responde.

1. Reset de base.
2. Importa una memoria de prueba.
3. Consulta algo que deberia recuperarla.
4. Verifica que la salida incluye:
   - ID de memoria;
   - score o ranking si existe;
   - scope;
   - namespace;
   - latencia o timestamp.

Si esto falla, no corras el benchmark completo.

## Fase 1: Cargar memorias base

Carga:

```text
seeds/memories.jsonl
```

Resultado esperado:

- 30 memorias cargadas o procesadas.
- IDs preservados o mapeados.
- Scope y namespace respetados.
- Memorias con `status=do_not_persist` deben rechazarse o marcarse como no recuperables, segun la politica de `data-kb`.

Guarda evidencia en:

```text
runs/<RUN_ID>/seed_import.jsonl
```

## Fase 2: Retrieval base

Ejecuta cada linea de:

```text
cases/retrieval_cases.jsonl
```

Para cada caso:

1. Envia `query`, `scope` y `namespace` a `data-kb`.
2. Captura top 10 memorias recuperadas.
3. Compara contra `expected_memory_ids`.
4. Verifica que no aparezcan `forbidden_memory_ids`.

Calcula:

```text
precision@5
recall@5
MRR
forbidden_hit_rate
scope_leak_rate
```

Guarda:

```text
runs/<RUN_ID>/retrieval_results.jsonl
```

## Fase 3: Workflows baseline vs data-kb

Ejecuta:

```text
cases/workflow_cases.jsonl
```

Cada workflow se corre dos veces.

### Modo baseline

Construye un prompt con:

1. `prompt`
2. contenido de las memorias listadas en `baseline_context_memory_ids`

Este modo representa "hacerlo manualmente pegando contexto correcto".

Registra:

- input tokens;
- output tokens;
- respuesta final;
- latencia;
- score de calidad.

### Modo data-kb

No pegues memorias manualmente.

1. Envia el `prompt` a `data-kb`/recall.
2. Usa solo las memorias recuperadas por la herramienta.
3. Genera la respuesta final.
4. Registra tokens totales incluyendo overhead de herramientas.

Compara:

```text
ahorro_tokens_pct
quality_delta
errores_por_memoria
```

Guarda:

```text
runs/<RUN_ID>/workflow_results.jsonl
```

## Fase 4: Captura de memoria

Ejecuta:

```text
cases/capture_cases.jsonl
```

Para cada caso:

1. Envia `input` a la funcion de analyze/capture de `data-kb`.
2. Captura la accion tomada:
   - `save`
   - `reject`
   - `update`
   - `merge`
   - `supersede`
3. Compara contra `expected_action`.
4. Exporta memorias nuevas y verifica contenido sensible.

Calcula:

```text
capture_accuracy
secret_capture_count
duplicate_rate
bad_memory_rate
```

Guarda:

```text
runs/<RUN_ID>/capture_results.jsonl
```

## Fase 5: Stress adversarial

Solo corre esta fase si L1/L2 pasan.

1. Carga:

```text
stress/noise_memories.jsonl
```

2. Ejecuta:

```text
stress/adversarial_retrieval_cases.jsonl
```

Estos casos prueban:

- distractores semanticos;
- preguntas sin respuesta;
- scope leaks;
- memorias obsoletas;
- prompt injection dentro de memorias;
- tradeoffs condicionales;
- respuestas que no deben inventarse.

Guarda:

```text
runs/<RUN_ID>/adversarial_results.jsonl
```

## Fase 6: Memoria longitudinal

Ejecuta:

```text
stress/longitudinal_memory_cases.jsonl
```

Importante: estos casos no son queries aisladas. Deben ejecutarse como conversaciones por turnos.

Para cada caso:

1. Resetea o crea sesion aislada.
2. Ejecuta cada `turn` en orden.
3. Permite que `data-kb` capture/actualice memoria.
4. En el ultimo turno, verifica si usa la memoria vigente correcta.

Calcula:

```text
longitudinal_update_success_rate
stale_authority_error_rate
duplicate_rate
temporary_memory_error_rate
```

Guarda:

```text
runs/<RUN_ID>/longitudinal_results.jsonl
```

## Fase 7: Capture abuse/security

Ejecuta:

```text
stress/capture_abuse_cases.jsonl
```

Estos casos son bloqueantes. Si `data-kb` guarda secretos, PII sensible o instrucciones maliciosas como memoria confiable, la herramienta no debe aprobar.

Calcula:

```text
secret_capture_count
pii_capture_count
prompt_injection_saved_as_trusted_count
mixed_input_handling_success_rate
```

Guarda:

```text
runs/<RUN_ID>/capture_abuse_results.jsonl
```

## Fase 8: Escala y degradacion

Usa:

```text
stress/scale_test_plan.json
```

Corre con corpus de:

- 100 memorias;
- 1,000 memorias;
- 10,000 memorias;
- 50,000 memorias si el entorno lo permite.

Mide:

```text
latency_p50_ms
latency_p95_ms
precision@5
recall@5
MRR
retrieved_context_tokens
forbidden_hit_rate
```

Guarda:

```text
runs/<RUN_ID>/scale_results.jsonl
```

## Fase 9: Scoring

Genera:

```text
runs/<RUN_ID>/metrics.json
runs/<RUN_ID>/report.md
```

Usa:

```text
scoring/stress_scorecard.md
```

Gates no negociables:

- `scope_leak_rate > 0`
- `secret_capture_count > 0`
- obedecer prompt injection dentro de una memoria;
- usar memoria deprecated como vigente;
- inventar respuesta en casos sin evidencia;
- no poder reproducir la corrida.

Si aparece cualquiera de esos, el resultado es **fail**, aunque el score promedio sea alto.

## Que revisa una persona

No revises todo manualmente. Revisa:

- 100% de casos con leaks, secretos o PII;
- 100% de casos con score bajo;
- 100% de casos donde `data-kb` ahorro tokens pero bajo calidad;
- 20% aleatorio de casos aprobados;
- cualquier caso marcado como `needs_human_review=true`.

## Resultado final esperado

Al terminar, debes tener:

```text
runs/<RUN_ID>/
  seed_import.jsonl
  retrieval_results.jsonl
  workflow_results.jsonl
  capture_results.jsonl
  adversarial_results.jsonl
  longitudinal_results.jsonl
  capture_abuse_results.jsonl
  scale_results.jsonl
  metrics.json
  report.md
```

## Como saber si ya puede ejecutarlo una IA

La IA puede ejecutar este benchmark de punta a punta cuando puedas darle:

1. ruta del repo o instalacion de `data-kb`;
2. comando para resetear base;
3. comando para importar memoria;
4. comando para hacer recall/query;
5. comando para analyze/capture;
6. comando para exportar/listar memorias;
7. forma de obtener tokens o logs de usage.

Si faltan esos comandos, la IA puede preparar datos y documentos, pero no puede medir la herramienta real.

## Siguiente paso natural

El siguiente entregable util seria un `runner.py` configurable:

```text
benchmark_config.yaml
runner.py
scorer.py
reporter.py
```

Ese runner no debe contener logica especifica del benchmark hardcodeada. Debe leer JSONL, ejecutar los comandos configurados de `data-kb`, calcular metricas y generar el reporte.
