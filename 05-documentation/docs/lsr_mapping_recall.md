# Grounded LSR mapping recall fix

The supplied facts were reproduced as: “Two 9.8 kg façade panels dropped from
approximately 22.35 m. Loose panels remained hanging overhead. Repeated references
to falling/dropped panels and dropped objects.” The original full report was not
provided.

Previously `reference_evidence` used only word/bigram TF-IDF cosine similarity,
with a 0.08 cutoff across the nine references and three glossary entries. This
reproduction scores 0.0738 for Line of Fire and is rejected. The catalog alias
`dropped object` does not normalize plural `objects`, relate panels to objects,
or express falling and loose overhead panels. Repeated unrelated report terms
also dilute cosine similarity. The UI derives mappings directly from retrieved
reference entries, so the empty result becomes “No supported mapping”. The
separate engine keyword list lacks dropped panels and includes overly broad
height/scaffold/load terms; it cannot repair grounded retrieval.

`lsr_concepts.py` now supplies versioned, curated contextual nominations for all
nine rules. Object-motion patterns distinguish falling objects from falling
people; crane operations and suspended-load exposure independently support
lifting and Line of Fire. Local negation and failure-specific isolation patterns
avoid interpreting verified isolation as failure. These deterministic patterns
are deliberately bounded and are not a general language understanding system.

Retrieval resolves nominations only against complete IOGP catalog entries.
Official text, identifiers, citations and corpus version are unchanged. TF-IDF
ranks independently supported entries without vetoing low lexical overlap.
Glossary retrieval keeps its existing lexical cutoff. Evidence includes original
report clauses, mapping version and a statement that mapping is not proof of a
violation. The relevance score remains lexical similarity, not confidence.
The API primary/secondary rules now use this grounded evidence after frozen
screening. No classifier, model, threshold or frozen validation artifact changed.

For the reproduction, primary is **Line of Fire**, secondary is empty. Evidence:
`IOGP-459-LINEOFFIRE`, IOGP Report 459 poster, page 1, “Keep yourself and others out
of the line of fire.” Retrieval method: `curated_concepts_tfidf`; alias version:
`lsr-concepts-v1`.

Regression coverage includes all nine rules, supplied panel facts, dropped tools,
person falls, independent crane/load mapping, verified and failed isolation,
ordinary and generic-word negatives, local negation, original narrative spans,
exact catalog provenance, missing-reference rejection, the analyze endpoint,
and identical frozen screening with and without mapping.

Validation: from `01-app/backend`, run
`.venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider`.
