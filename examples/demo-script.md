---
title: How Retrieval-Augmented Generation Works
voice: en-US-AriaNeural
palette: midnight
---

## Frozen Knowledge

Large language models are trained once, then deployed for months.
Ask one about yesterday's release notes and it will either admit
ignorance or, worse, invent a confident answer. The model is not
broken. Its knowledge is simply frozen at training time.

## Retrieval in One Sentence
<!-- s2v: palette=aurora -->

Retrieval-augmented generation, or RAG, fixes this with one move:
before the model answers, fetch the most relevant documents from your
own knowledge base, and hand them to the model as part of the prompt.

## Chunk, Embed, Store
<!-- s2v: palette=kelp -->

Preparation happens offline. Documents are split into small
overlapping chunks. Each chunk is converted into an embedding, a
vector that captures its meaning. Those vectors go into an index
built for fast similarity search.

## The Grounded Prompt
<!-- s2v: palette=ember -->

At question time, the query is embedded the same way, the nearest
chunks are retrieved, and the model receives both the question and
the evidence. Its job shifts from recalling facts to reading and
synthesizing them, with sources it can cite.

## Why It Matters
<!-- s2v: palette=dawn -->

Answers stay current without retraining. Every claim can be traced
back to a document. And because the knowledge lives outside the
model, a smaller, cheaper model with good retrieval often beats a
giant one working from memory alone.
