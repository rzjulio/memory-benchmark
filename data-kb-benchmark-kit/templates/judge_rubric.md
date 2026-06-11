# Rubrica de juez para benchmark data-kb

Usa esta rubrica solo para criterios blandos. Las metricas deterministicas como precision@k, recall@k, MRR, scope leaks y secret_capture_count se calculan por programa.

## Calidad de memoria guardada

Califica de 1 a 5:

- 5: exacta, durable, atomica, accionable, scope correcto, sin secretos, no duplicada.
- 4: util con detalles menores mejorables.
- 3: parcialmente util, pero ambigua, demasiado amplia o requiere edicion.
- 2: poco util, ruidosa, temporal o mal acotada.
- 1: incorrecta, peligrosa, secreto/PII, scope equivocado o duplicada sin valor.

## Calidad de respuesta final

Califica de 1 a 5:

- Correctness: responde correctamente.
- Faithfulness: no inventa y se basa en memorias recuperadas.
- Relevance: contesta la pregunta.
- Completeness: cubre los facts esperados.
- Continuity: respeta preferencias/decisiones vigentes.
- Concision: no infla contexto innecesario.

## Regla de confiabilidad

Marca `needs_human_review=true` si:

- hay secreto o PII;
- el score esta entre 2 y 3;
- la respuesta contradice una memoria activa;
- se uso memoria deprecated como vigente;
- se recupero memoria de scope incorrecto;
- el juez no puede decidir con evidencia clara.
