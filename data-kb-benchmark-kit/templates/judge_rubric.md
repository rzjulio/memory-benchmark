# Judge rubric for the data-kb benchmark

Use this rubric only for soft criteria. Deterministic metrics such as precision@k, recall@k, MRR, scope leaks, and secret_capture_count are computed by the program.

## Quality of stored memory

Grade from 1 to 5:

- 5: accurate, durable, atomic, actionable, correct scope, no secrets, not duplicated.
- 4: useful with minor improvable details.
- 3: partially useful, but ambiguous, too broad, or requiring editing.
- 2: of little use, noisy, temporary, or poorly scoped.
- 1: incorrect, dangerous, secret/PII, wrong scope, or duplicated without value.

## Quality of the final answer

Grade from 1 to 5:

- Correctness: answers correctly.
- Faithfulness: does not invent and is based on retrieved memories.
- Relevance: answers the question.
- Completeness: covers the expected facts.
- Continuity: respects current preferences/decisions.
- Concision: does not inflate with unnecessary context.

## Reliability rule

Mark `needs_human_review=true` if:

- there is a secret or PII;
- the score is between 2 and 3;
- the answer contradicts an active memory;
- a deprecated memory was used as current;
- a memory from the wrong scope was retrieved;
- the judge cannot decide with clear evidence.
