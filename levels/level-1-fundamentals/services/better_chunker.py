import re

class BetterChunker:
    def split_sentences(self, text):
        text = text.strip()
        if not text:
            return []

        sentences = re.split(r"(?<=[.!?])\s+", text)

        return [sentence.strip() for sentence in sentences if sentence.strip()]

    def build_chunks(self, sentences, max_chunk_size=500, overlap_sentences=0):
        if max_chunk_size <= 0:
            raise ValueError("max_chunk_size must be greater than 0")

        if overlap_sentences < 0:
            raise ValueError("overlap_sentences cannot be negative")

        chunks = []
        current_sentences = []
        current_length = 0

        for sentence in sentences:
            sentence_length = len(sentence)

            if sentence_length > max_chunk_size:

                if current_sentences:
                    chunks.append(" ".join(current_sentences))
                    if overlap_sentences == 0:
                        current_sentences = []
                    else:
                        current_sentences = current_sentences[-overlap_sentences:]

                    current_length = len(" ".join(current_sentences))

                for start in range(0, sentence_length, max_chunk_size):
                    piece = sentence[start:start+max_chunk_size]
                    chunks.append(piece)

                current_length = 0
                current_sentences = []
                continue

            if current_length + sentence_length + len(current_sentences) <= max_chunk_size:
                current_sentences.append(sentence)
                current_length += sentence_length
            else:
                chunks.append(" ".join(current_sentences))

                if overlap_sentences == 0:
                    current_sentences = [sentence]
                else:
                    overlapped_sentences = current_sentences[-overlap_sentences:]
                    potencial_chunk = " ".join(overlapped_sentences+[sentence])

                    if len(potencial_chunk) <= max_chunk_size:
                        current_sentences = overlapped_sentences + [sentence]
                    else:
                        current_sentences = [sentence]

                current_length = len(" ".join(current_sentences))

        if current_sentences:
            chunks.append(" ".join(current_sentences))

        return chunks
