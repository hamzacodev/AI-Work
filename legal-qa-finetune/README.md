# legal-qa-finetune

Fine-tune a small open-source LLM (Llama 3.2 3B) to answer UK legal questions, add RAG, and compare approaches with real evaluation numbers.

**Not legal advice.** This is a learning project.

## Approaches compared
- A: plain Llama
- B: Llama + RAG
- C: fine-tuned Llama
- D: fine-tuned Llama + RAG
- E: free API model (Gemini or Groq) as a reference

## Stages
1. Data (`data/`)
2. Evaluation set (`eval/`)
3. RAG (`rag/`)
4. Fine-tune (`finetune/`)
5. Compare A to E
6. Gradio demo (`app/`)
7. Results and architecture diagram (this README)

Status: Stage 1 not started.
